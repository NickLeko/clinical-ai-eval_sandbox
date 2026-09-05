import argparse
import json
import os
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.artifact_paths import build_artifact_paths
from src.artifact_integrity import validate_scored_artifacts, seal_summary


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def safe_mean(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(series.mean())


def load_run_manifest(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing run manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def benchmark_status(manifest: dict) -> str:
    status = str(manifest.get("benchmark_status", "")).strip().lower()
    if status:
        return status

    run_kind = str(manifest.get("run_kind", "")).strip().lower()
    provider = str(manifest.get("provider", "")).strip().lower()
    is_full_dataset_run = bool(manifest.get("is_full_dataset_run", True))
    if run_kind == "published" and provider != "mock" and is_full_dataset_run:
        return "canonical_published"
    if run_kind == "candidate" and provider != "mock" and is_full_dataset_run:
        return "published_candidate"
    return "sandbox"


def build_grade_breakdown(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    if group_col not in df.columns:
        return pd.DataFrame()

    working = df[[group_col, "overall_grade"]].copy()
    working[group_col] = working[group_col].fillna("").astype(str)
    working = working[working[group_col] != ""]
    if working.empty:
        return pd.DataFrame()

    grouped = (
        working.groupby([group_col, "overall_grade"])
        .size()
        .unstack(fill_value=0)
    )
    for grade in ["PASS", "WARN", "FAIL"]:
        if grade not in grouped.columns:
            grouped[grade] = 0
    grouped["total"] = grouped[["PASS", "WARN", "FAIL"]].sum(axis=1)
    grouped = grouped.reset_index()
    return grouped[[group_col, "total", "PASS", "WARN", "FAIL"]].sort_values(by=[group_col], ascending=[True])


def append_breakdown_table(lines: list[str], title: str, label: str, table: pd.DataFrame) -> None:
    lines.append(f"\n## {title}\n")
    if table.empty:
        lines.append("- (not available)\n")
        return

    lines.append(f"| {label} | total | PASS | WARN | FAIL |\n")
    lines.append("|---|---:|---:|---:|---:|\n")
    for _, row in table.iterrows():
        lines.append(
            f"| {row[label]} | {int(row['total'])} | {int(row['PASS'])} | {int(row['WARN'])} | {int(row['FAIL'])} |\n"
        )


def main(top_n: int, results_dir: str) -> None:
    paths = build_artifact_paths(results_dir)
    receipt = validate_scored_artifacts(results_dir)
    if not paths.evaluation_output_path.exists():
        raise FileNotFoundError(f"Missing file: {paths.evaluation_output_path}")

    df = pd.read_csv(paths.evaluation_output_path)
    manifest = load_run_manifest(paths.run_manifest_path)

    if "failure_tags" in df.columns:
        df["failure_tags"] = df["failure_tags"].fillna("").astype(str)

    # Safety signal subsets
    unsafe_cases = df[df["unsafe_recommendation"] == True]
    halluc_cases = df[df["hallucination_suspected"] == True]
    refusal_cases = df[df["refusal_failure"] == True]
    
    # Safety signal rates
    unsafe_rate = len(unsafe_cases) / max(len(df), 1)
    halluc_rate = len(halluc_cases) / max(len(df), 1)
    refusal_rate = len(refusal_cases) / max(len(df), 1)


    # Normalize
    for col in [
        "format_compliance",
        "citation_validity",
        "required_citations",
        "uncertainty_alignment",
        "gold_key_points_coverage",
        "faithfulness_proxy",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    total = len(df)
    if total == 0:
        raise ValueError("evaluation_output.csv is empty")

    status = benchmark_status(manifest)
    canonical_published = status == "canonical_published"
    dataset_total_rows = int(manifest.get("dataset_total_rows", manifest.get("case_count", total)))
    case_count = int(manifest.get("case_count", total))
    is_full_dataset_run = bool(manifest.get("is_full_dataset_run", case_count == dataset_total_rows))

    grade_counts = df["overall_grade"].value_counts(dropna=False).to_dict()

    pass_rate = (df["overall_grade"] == "PASS").mean()
    warn_rate = (df["overall_grade"] == "WARN").mean()
    fail_rate = (df["overall_grade"] == "FAIL").mean()

    metric_means = {
        "faithfulness_proxy": safe_mean(df["faithfulness_proxy"]) if "faithfulness_proxy" in df else 0.0,
        "citation_validity": safe_mean(df["citation_validity"]) if "citation_validity" in df else 0.0,
        "required_citations": safe_mean(df["required_citations"]) if "required_citations" in df else 0.0,
        "uncertainty_alignment": safe_mean(df["uncertainty_alignment"]) if "uncertainty_alignment" in df else 0.0,
        "gold_key_points_coverage": safe_mean(df["gold_key_points_coverage"]) if "gold_key_points_coverage" in df else 0.0,
        "format_compliance": safe_mean(df["format_compliance"]) if "format_compliance" in df else 0.0,
    }

    # Failure tags
    tags = (
        df["failure_tags"]
        .fillna("")
        .astype(str)
        .str.split("|")
        .explode()
    )
    tags = tags[tags != ""]
    tag_counts = tags.value_counts().to_dict()

    # Worst cases by grade then by faithfulness
    grade_rank = {"FAIL": 0, "WARN": 1, "PASS": 2}
    df["_grade_rank"] = df["overall_grade"].map(grade_rank).fillna(9)
    df_sorted = df.sort_values(
        by=["_grade_rank", "faithfulness_proxy", "case_id"],
        ascending=[True, True, True],
    )

    worst = df_sorted.head(top_n)[
        [
            "case_id",
            "category",
            "risk_level",
            "model_id",
            "prompt_version",
            "overall_grade",
            "faithfulness_proxy",
            "uncertainty_alignment",
            "failure_tags",
        ]
    ]

    category_breakdown = build_grade_breakdown(df, "category")
    risk_breakdown = build_grade_breakdown(df, "risk_level")

    lines = []
    lines.append(f"# Clinical AI Evaluation Sandbox — Summary\n")
    if status == "canonical_published":
        run_label = "Published run"
    elif status == "published_candidate":
        run_label = "Benchmark candidate"
    else:
        run_label = "Run"
    lines.append(f"_{run_label}: `{manifest['provider']}` / `{manifest['model_id']}` / `{manifest['run_id']}`_\n")
    lines.append("\n## Run Identity\n")
    lines.append(f"- Provider: **{manifest['provider']}**\n")
    lines.append(f"- Model: **{manifest['model_id']}**\n")
    lines.append(f"- Run ID: **{manifest['run_id']}**\n")
    lines.append(f"- Prompt version: **{manifest['prompt_version']}**\n")
    lines.append(f"- Run kind: **{manifest.get('run_kind', 'published' if canonical_published else 'sandbox')}**\n")
    lines.append(f"- Cases in this run: **{case_count}**\n")
    lines.append(f"- Dataset coverage: **{case_count} / {dataset_total_rows}** cases\n")
    if manifest.get("source_run_ids"):
        lines.append(f"- Source generation run ids: **{', '.join(manifest['source_run_ids'])}**\n")

    lines.append("\n## Benchmark Status\n")
    if status == "canonical_published":
        lines.append("- Status: **Canonical published benchmark run**\n")
    elif status == "published_candidate":
        lines.append("- Status: **Published benchmark candidate (non-canonical)**\n")
        lines.append("- This run is a review candidate and should not replace the checked-in published benchmark artifacts without review.\n")
    else:
        lines.append("- Status: **Sandbox / non-canonical run**\n")
        lines.append("- This run should not replace the checked-in published benchmark artifacts without review.\n")
    if not is_full_dataset_run:
        lines.append("- This run used only a subset of the dataset and is not comparable to the full published benchmark.\n")
    if str(manifest.get("provider", "")).strip().lower() == "mock":
        lines.append("- This run used the `mock` provider and is intended for pipeline validation or exploratory review.\n")

    lines.append("\n## Scorecard\n")
    lines.append(f"- Blocking adversarial acceptance suite: **PASS ({receipt['acceptance']['tests_run']} tests; no skips or expected failures)**\n")
    lines.append("- This contract covers literal-action minimal pairs and a mock canary; it is not a clinical safety measurement.\n")
    lines.append(f"- Total cases scored: **{total}**\n")
    lines.append(f"- PASS: **{grade_counts.get('PASS', 0)}** ({pct(pass_rate)})\n")
    lines.append(f"- WARN: **{grade_counts.get('WARN', 0)}** ({pct(warn_rate)})\n")
    lines.append(f"- FAIL: **{grade_counts.get('FAIL', 0)}** ({pct(fail_rate)})\n")
    lines.append(f"- Incomplete generations: **{int((df['generation_status'] != 'complete').sum())}** (execution failures; partial-text scores are diagnostic only)\n")
    lines.append("\n## Interpretation Guardrail\n")
    lines.append("- This run is a heuristic benchmark artifact, not evidence of clinical safety or deployment readiness.\n")
    lines.append("- The current evaluator uses non-empty section checks and rationale-scoped required citations.\n")
    lines.append("- Historical cached generations are stored separately under `results/cache/` and are not the published benchmark set.\n")
    lines.append("\n## Heuristic Signal Rates\n")
    lines.append(f"- Unsafe recommendation rate: **{unsafe_rate:.1%}**\n")
    lines.append(f"- Hallucination suspicion rate: **{halluc_rate:.1%}**\n")
    lines.append(f"- Refusal failure rate: **{refusal_rate:.1%}**\n")
    lines.append(f"\n## Mean metric scores\n")
    for k, v in metric_means.items():
        lines.append(f"- {k}: **{v:.3f}**\n")
    lines.append("- `gold_key_points_coverage` is a supporting checklist-style metric and should be read alongside the other scores and flagged cases.\n")

    append_breakdown_table(lines, "Category Breakdown", "category", category_breakdown)
    append_breakdown_table(lines, "Risk Breakdown", "risk_level", risk_breakdown)

    lines.append(f"\n## Failure tag counts\n")
    if not tag_counts:
        lines.append("- (none)\n")
    else:
        for tag, count in sorted(tag_counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- {tag}: **{count}**\n")

    lines.append(f"\n## Worst cases (top {top_n})\n")
    lines.append("| case_id | category | risk | model | prompt | grade | faithfulness | uncertainty | tags |\n")
    lines.append("|---|---|---|---|---|---|---:|---:|---|\n")
    for _, r in worst.iterrows():
        lines.append(
            f"| {r['case_id']} | {r.get('category','')} | {r.get('risk_level','')} | {r.get('model_id','')} | "
            f"{r.get('prompt_version','')} | {r.get('overall_grade','')} | {float(r.get('faithfulness_proxy',0.0)):.3f} | "
            f"{float(r.get('uncertainty_alignment',0.0)):.3f} | {r.get('failure_tags','')} |\n"
        )

    os.makedirs(results_dir, exist_ok=True)
    with paths.summary_output_path.open("w", encoding="utf-8") as f:
        f.write("".join(lines))
    seal_summary(results_dir)

    print(f"Wrote: {paths.summary_output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Summarize evaluation results into Markdown.")
    parser.add_argument("--top-n", type=int, default=10, help="Number of worst cases to list.")
    parser.add_argument(
        "--results-dir",
        default="results",
        help="Directory containing evaluated run artifacts, such as results/ or sandbox_results/.",
    )
    args = parser.parse_args()

    main(top_n=args.top_n, results_dir=args.results_dir)
