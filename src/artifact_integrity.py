"""Fail-closed bindings between scored inputs, outputs, code, and summary.

Receipts detect stale/mixed files; they are not signed attestations against a writer
who controls the entire artifact bundle. Only the evaluator should seal evaluations.
"""
import csv
import hashlib
import json
from pathlib import Path

from src.acceptance import contract_identity
from src.llm_clients import validate_generation_payload
from src.version import __version__

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = "evaluation_manifest.json"
BOUND_FILES = ("run_manifest.json", "raw_generations.jsonl", "evaluation_output.csv", "flagged_cases.jsonl")
REQUIRED_COLUMNS = {"case_id", "run_id", "provider", "model_id", "prompt_version", "overall_grade",
                    "failure_tags", "unsafe_recommendation", "hallucination_suspected", "refusal_failure",
                    "generation_status", "finish_reason"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evaluator_identity():
    return {f"src/{name}": sha256(ROOT / "src" / name) for name in
            ("metrics.py", "run_evaluation.py", "artifact_integrity.py", "llm_clients.py",
             "prompt_templates.py", "generate_answers.py", "version.py")}


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def seal_evaluation(results_dir, acceptance):
    root = Path(results_dir)
    write_json(root / RECEIPT, {"schema_version": 1, "release_version": __version__,
                              "evaluator": evaluator_identity(), "acceptance": acceptance,
                              "files": {name: sha256(root / name) for name in BOUND_FILES}})


def validate_scored_artifacts(results_dir, *, require_summary=False):
    root = Path(results_dir)
    path = root / RECEIPT
    if not path.exists():
        raise ValueError("Unscored or legacy artifacts: missing evaluation_manifest.json; rerun evaluation and summary")
    receipt = json.loads(path.read_text())
    if receipt.get("schema_version") != 1 or receipt.get("evaluator") != evaluator_identity():
        raise ValueError("Stale evaluation: evaluator identity changed; rerun evaluation and summary")
    acceptance = receipt.get("acceptance", {})
    if (acceptance.get("identity") != contract_identity() or acceptance.get("status") != "PASS"
            or acceptance.get("tests_run", 0) <= 0 or acceptance.get("failures") != 0
            or acceptance.get("errors") != 0 or acceptance.get("expected_failures") != 0
            or acceptance.get("skipped") != 0):
        raise ValueError("Missing or stale blocking acceptance result")
    for name in BOUND_FILES:
        if not (root / name).exists() or receipt.get("files", {}).get(name) != sha256(root / name):
            raise ValueError(f"Stale or unscored {name}; rerun evaluation and summary")
    manifest = json.loads((root / "run_manifest.json").read_text())
    dataset = Path(manifest.get("dataset_path", ""))
    if not dataset.is_absolute():
        dataset = ROOT / dataset
    if not dataset.is_file() or sha256(dataset) != manifest.get("dataset_sha256"):
        raise ValueError("Dataset contents do not match the run manifest")
    with (root / "evaluation_output.csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        if not REQUIRED_COLUMNS.issubset(reader.fieldnames or []):
            raise ValueError("evaluation_output.csv missing required identity/status/safety columns")
        evaluated = list(reader)
    raw = [json.loads(line) for line in (root / "raw_generations.jsonl").read_text().splitlines() if line.strip()]
    expected_ids = manifest.get("case_ids")
    if (not expected_ids or len(set(expected_ids)) != len(expected_ids)
            or len(expected_ids) != manifest.get("case_count")
            or [r.get("case_id") for r in evaluated] != expected_ids
            or [r.get("case_id") for r in raw] != expected_ids):
        raise ValueError("Scored/raw case coverage does not match run manifest")
    for generated, scored in zip(raw, evaluated):
        for field in ("run_id", "provider", "model_id", "prompt_version"):
            if scored.get(field) != manifest.get(field) or generated.get(field) != manifest.get(field):
                raise ValueError(f"{field} does not match run manifest")
        metadata = validate_generation_payload(generated)
        if any(scored.get(key) != value for key, value in metadata.items()):
            raise ValueError("Scored completion status does not match raw response")
        for key in ("unsafe_recommendation", "hallucination_suspected", "refusal_failure"):
            if scored[key] not in {"True", "False"}:
                raise ValueError(f"Invalid safety flag: {key}")
        if scored["overall_grade"] not in {"PASS", "WARN", "FAIL"}:
            raise ValueError("Invalid overall grade")
        if metadata["generation_status"] != "complete" and scored["overall_grade"] != "FAIL":
            raise ValueError("Incomplete generation cannot have a passing scored status")
    flagged = [json.loads(line) for line in (root / "flagged_cases.jsonl").read_text().splitlines() if line.strip()]
    expected_flagged = [r for r in evaluated if r["overall_grade"] in {"WARN", "FAIL"}]
    if [r.get("case_id") for r in flagged] != [r["case_id"] for r in expected_flagged]:
        raise ValueError("flagged_cases.jsonl does not contain the complete WARN/FAIL subset")
    raw_by_id = {r["case_id"]: r for r in raw}
    for item, scored in zip(flagged, expected_flagged):
        for field in ("model_id", "prompt_version", "overall_grade", "failure_tags"):
            if item.get(field) != scored[field]:
                raise ValueError(f"flagged_cases.jsonl {field} mismatch")
        if item.get("answer_text") != raw_by_id[item["case_id"]]["answer_text"]:
            raise ValueError("flagged answer_text does not match scored raw text")
    if require_summary:
        summary = receipt.get("summary", {})
        if (not (root / "summary.md").is_file() or summary.get("sha256") != sha256(root / "summary.md")
                or summary.get("producer_sha256") != sha256(ROOT / "src/summarize_results.py")):
            raise ValueError("Stale or missing summary.md; rerun summary")
    return receipt


def seal_summary(results_dir):
    root = Path(results_dir)
    receipt = validate_scored_artifacts(root)
    receipt["summary"] = {"sha256": sha256(root / "summary.md"),
                          "producer_sha256": sha256(ROOT / "src/summarize_results.py")}
    write_json(root / RECEIPT, receipt)
