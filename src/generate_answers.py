import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from tqdm import tqdm

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.artifact_paths import build_artifact_paths
from src.llm_clients import AnthropicClient, GeminiClient, MockClient, OpenAIClient
from src.prompt_templates import build_clinical_prompt


SUPPORTED_PROVIDERS = ("openai", "anthropic", "gemini", "mock")
CANONICAL_RESULTS_DIR = (Path(__file__).resolve().parents[1] / "results").resolve()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def sha256_file(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def default_run_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def resolve_results_dir(results_dir: Optional[str], run_kind: str, run_id: str) -> str:
    if results_dir is not None:
        return results_dir
    if run_kind == "sandbox":
        return str(Path("sandbox_results") / run_id)
    return "results"


def validate_results_dir_request(results_dir: str, run_kind: str, confirm_published: bool) -> None:
    if Path(results_dir).resolve() != CANONICAL_RESULTS_DIR:
        return

    if run_kind in ("sandbox", "candidate"):
        raise ValueError(f"{run_kind.capitalize()} runs cannot write to the canonical results/ directory.")
    if run_kind == "published" and not confirm_published:
        raise ValueError("Published writes to the canonical results/ directory require --confirm-published.")


def classify_benchmark_status(run_kind: str, provider: str, is_full_dataset_run: bool) -> str:
    if run_kind == "published" and provider != "mock" and is_full_dataset_run:
        return "canonical_published"
    if run_kind == "candidate" and provider != "mock" and is_full_dataset_run:
        return "published_candidate"
    return "sandbox"


def ensure_results_dirs(results_dir: str) -> None:
    paths = build_artifact_paths(results_dir)
    paths.results_dir.mkdir(parents=True, exist_ok=True)
    paths.cache_dir.mkdir(parents=True, exist_ok=True)


def build_cache_key(case_id: str, provider: str, model_id: str, prompt_version: str, prompt: str) -> str:
    cache_scope = f"{case_id}|{provider}|{model_id}|{prompt_version}|{prompt}"
    return stable_hash(cache_scope)


def load_existing_cache(path: Path) -> Dict[str, Dict[str, Any]]:
    """
    Loads reusable raw generations keyed by provider/model/prompt identity.
    """
    if not path.exists():
        return {}

    cache: Dict[str, Dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            try:
                cache_key = build_cache_key(
                    case_id=str(row["case_id"]),
                    provider=str(row["provider"]),
                    model_id=str(row["model_id"]),
                    prompt_version=str(row["prompt_version"]),
                    prompt=str(row["prompt"]),
                )
            except KeyError:
                continue
            row["cache_key"] = cache_key
            cache[cache_key] = row
    return cache


def write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return

    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_provider_name(provider: str) -> str:
    return str(provider).strip().lower()


def select_client(provider: str, model_id: str):
    provider_name = normalize_provider_name(provider)
    client_factories = {
        "openai": lambda: OpenAIClient(model=model_id),
        "anthropic": lambda: AnthropicClient(model=model_id),
        "gemini": lambda: GeminiClient(model=model_id),
        "mock": MockClient,
    }

    if provider_name not in client_factories:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        raise ValueError(f"Unknown provider: {provider}. Supported providers: {supported}")

    return client_factories[provider_name]()


def validate_run_request(
    *,
    provider: str,
    run_kind: str,
    dataset_total_rows: int,
    selected_case_count: int,
) -> None:
    provider = normalize_provider_name(provider)
    if selected_case_count <= 0:
        raise ValueError("No dataset rows selected for generation.")

    if run_kind in ("candidate", "published") and provider == "mock":
        raise ValueError(f"{run_kind.capitalize()} benchmark runs cannot use the mock provider.")

    if run_kind in ("candidate", "published") and selected_case_count != dataset_total_rows:
        raise ValueError(
            f"{run_kind.capitalize()} benchmark runs must score the full dataset. "
            f"Selected {selected_case_count} of {dataset_total_rows} rows."
        )


def build_public_row_from_cache(
    cached_row: Dict[str, Any],
    run_id: str,
    provider: str,
    model_id: str,
    prompt_version: str,
    cache_key: str,
) -> Dict[str, Any]:
    source_run_id = str(cached_row.get("run_id", ""))
    generation_mode = "exact_run_reuse" if source_run_id == run_id else "cache_reuse"

    return {
        "run_id": run_id,
        "timestamp_utc": cached_row.get("timestamp_utc", ""),
        "source_run_id": source_run_id,
        "source_timestamp_utc": cached_row.get("timestamp_utc", ""),
        "case_id": cached_row.get("case_id", ""),
        "provider": provider,
        "model_id": model_id,
        "prompt_version": prompt_version,
        "cache_key": cache_key,
        "prompt": cached_row.get("prompt", ""),
        "answer_text": cached_row.get("answer_text", ""),
        "latency_ms": cached_row.get("latency_ms", 0),
        "generation_mode": generation_mode,
        "raw_response": cached_row.get("raw_response", {}),
    }


def build_live_row(
    *,
    run_id: str,
    case_id: str,
    provider: str,
    model_id: str,
    prompt_version: str,
    cache_key: str,
    prompt: str,
    response: Dict[str, Any],
    latency_ms: int,
) -> Dict[str, Any]:
    timestamp_utc = utc_now_iso()
    return {
        "run_id": run_id,
        "timestamp_utc": timestamp_utc,
        "source_run_id": run_id,
        "source_timestamp_utc": timestamp_utc,
        "case_id": case_id,
        "provider": provider,
        "model_id": model_id,
        "prompt_version": prompt_version,
        "cache_key": cache_key,
        "prompt": prompt,
        "answer_text": response.get("answer_text", ""),
        "latency_ms": latency_ms,
        "generation_mode": "live_generation",
        "raw_response": response.get("raw_response", {}),
    }


def build_run_manifest(
    *,
    dataset_path: str,
    provider: str,
    model_id: str,
    prompt_version: str,
    run_id: str,
    run_kind: str,
    rows: List[Dict[str, Any]],
    results_dir: str,
    public_raw_path: str,
    cache_raw_path: str,
    dataset_total_rows: int,
    is_full_dataset_run: bool,
    cache_hits: int,
    live_generations: int,
) -> Dict[str, Any]:
    generation_modes = Counter(row.get("generation_mode", "") for row in rows)
    source_run_ids = sorted({str(row.get("source_run_id", "")) for row in rows if row.get("source_run_id")})
    source_timestamps = sorted(
        {str(row.get("source_timestamp_utc", "")) for row in rows if row.get("source_timestamp_utc")}
    )

    return {
        "run_id": run_id,
        "provider": provider,
        "model_id": model_id,
        "prompt_version": prompt_version,
        "run_kind": run_kind,
        "benchmark_status": classify_benchmark_status(run_kind, provider, is_full_dataset_run),
        "dataset_path": dataset_path,
        "dataset_sha256": sha256_file(dataset_path),
        "dataset_total_rows": dataset_total_rows,
        "is_full_dataset_run": is_full_dataset_run,
        "results_dir": results_dir,
        "public_raw_path": public_raw_path,
        "cache_raw_path": cache_raw_path,
        "case_count": len(rows),
        "case_ids": [row["case_id"] for row in rows],
        "cache_hits": cache_hits,
        "live_generations": live_generations,
        "generation_modes": dict(generation_modes),
        "source_run_ids": source_run_ids,
        "source_timestamps_utc": source_timestamps,
    }


def main(
    dataset_path: str,
    provider: str,
    model_id: str,
    prompt_version: str,
    run_id: Optional[str],
    max_cases: Optional[int],
    sleep_s: float,
    results_dir: Optional[str],
    run_kind: str = "sandbox",
    confirm_published: bool = False,
) -> None:
    provider = normalize_provider_name(provider)
    requested_run_id = run_id or default_run_id()
    results_dir = resolve_results_dir(results_dir, run_kind, requested_run_id)
    validate_results_dir_request(results_dir, run_kind, confirm_published)
    ensure_results_dirs(results_dir)
    paths = build_artifact_paths(results_dir)

    df = pd.read_csv(dataset_path)
    if "case_id" not in df.columns:
        raise ValueError("Dataset must include a 'case_id' column")
    if df.empty:
        raise ValueError("Dataset is empty.")
    if df["case_id"].duplicated().any():
        dupes = sorted(df[df["case_id"].duplicated()]["case_id"].astype(str).unique().tolist())
        raise ValueError(f"Dataset contains duplicate case_id values: {dupes}")

    dataset_total_rows = len(df)

    # Optional cap (cost control)
    if max_cases is not None:
        df = df.head(max_cases)

    selected_case_count = len(df)
    validate_run_request(
        provider=provider,
        run_kind=run_kind,
        dataset_total_rows=dataset_total_rows,
        selected_case_count=selected_case_count,
    )
    is_full_dataset_run = selected_case_count == dataset_total_rows

    existing = load_existing_cache(paths.cache_raw_path)

    public_rows: List[Dict[str, Any]] = []
    new_cache_rows: List[Dict[str, Any]] = []
    client = None
    cache_hits = 0
    live_generations = 0

    for _, row in tqdm(df.iterrows(), total=len(df), desc="Generating"):
        case_id = str(row["case_id"])
        question = str(row.get("question", ""))
        context = str(row.get("provided_context", ""))

        prompt = build_clinical_prompt(question=question, context=context)
        cache_key = build_cache_key(case_id, provider, model_id, prompt_version, prompt)

        if cache_key in existing:
            public_rows.append(
                build_public_row_from_cache(
                    cached_row=existing[cache_key],
                    run_id=requested_run_id,
                    provider=provider,
                    model_id=model_id,
                    prompt_version=prompt_version,
                    cache_key=cache_key,
                )
            )
            cache_hits += 1
            continue

        if client is None:
            client = select_client(provider, model_id)

        t0 = time.time()
        try:
            resp = client.generate(prompt)
        except Exception as exc:
            print(
                "Generation failed "
                f"(case_id={case_id}, provider={provider}, model={model_id}, prompt_version={prompt_version}): {exc}"
            )
            raise
        latency_ms = int((time.time() - t0) * 1000)

        live_row = build_live_row(
            run_id=requested_run_id,
            case_id=case_id,
            provider=provider,
            model_id=model_id,
            prompt_version=prompt_version,
            cache_key=cache_key,
            prompt=prompt,
            response=resp,
            latency_ms=latency_ms,
        )
        public_rows.append(live_row)
        new_cache_rows.append(live_row)
        existing[cache_key] = live_row
        live_generations += 1

        if sleep_s > 0:
            time.sleep(sleep_s)

    manifest = build_run_manifest(
        dataset_path=dataset_path,
        provider=provider,
        model_id=model_id,
        prompt_version=prompt_version,
        run_id=requested_run_id,
        run_kind=run_kind,
        rows=public_rows,
        results_dir=results_dir,
        public_raw_path=str(paths.public_raw_path),
        cache_raw_path=str(paths.cache_raw_path),
        dataset_total_rows=dataset_total_rows,
        is_full_dataset_run=is_full_dataset_run,
        cache_hits=cache_hits,
        live_generations=live_generations,
    )

    write_jsonl(paths.public_raw_path, public_rows)
    append_jsonl(paths.cache_raw_path, new_cache_rows)
    paths.run_manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"Done. Public raw generations at: {paths.public_raw_path}")
    print(f"Cache store at: {paths.cache_raw_path}")
    print(f"Run manifest at: {paths.run_manifest_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate LLM answers for clinical eval dataset.")
    parser.add_argument("--dataset", default="dataset/clinical_questions.csv", help="Path to dataset CSV.")
    parser.add_argument("--provider", default="openai", choices=list(SUPPORTED_PROVIDERS), help="LLM provider.")
    parser.add_argument("--model", default="gpt-4o", help="Model id (provider-specific).")
    parser.add_argument("--prompt-version", default="v1", help="Prompt template version string.")
    parser.add_argument("--run-id", default=None, help="Explicit run identifier.")
    parser.add_argument("--max-cases", type=int, default=None, help="Max number of cases to run (cost control).")
    parser.add_argument("--sleep-s", type=float, default=0.0, help="Sleep between calls (rate-limit friendliness).")
    parser.add_argument(
        "--results-dir",
        default=None,
        help="Directory for public and cached artifacts. Sandbox runs default to sandbox_results/<run_id>/.",
    )
    parser.add_argument(
        "--run-kind",
        default="sandbox",
        choices=["sandbox", "candidate", "published"],
        help=(
            "Run intent: sandbox for exploratory/non-canonical runs, candidate for full-dataset review artifacts, "
            "published for the checked-in canonical artifact set."
        ),
    )
    parser.add_argument(
        "--confirm-published",
        action="store_true",
        help="Confirm an intentional published write to the canonical results/ directory.",
    )
    args = parser.parse_args()

    main(
        dataset_path=args.dataset,
        provider=args.provider,
        model_id=args.model,
        prompt_version=args.prompt_version,
        run_id=args.run_id,
        max_cases=args.max_cases,
        sleep_s=args.sleep_s,
        results_dir=args.results_dir,
        run_kind=args.run_kind,
        confirm_published=args.confirm_published,
    )
