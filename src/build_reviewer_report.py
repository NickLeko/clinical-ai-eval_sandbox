import argparse
import csv
import hashlib
import html as html_lib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.artifact_paths import (
    EVALUATION_OUTPUT_FILENAME,
    FLAGGED_OUTPUT_FILENAME,
    PUBLIC_RAW_FILENAME,
    RUN_MANIFEST_FILENAME,
    SUMMARY_OUTPUT_FILENAME,
    build_artifact_paths,
)


REVIEWER_PACKAGE_SCHEMA_VERSION = "reviewer-package-v1"
REVIEWER_REPORT_FILENAME = "reviewer_report.html"
REVIEWER_SUMMARY_FILENAME = "reviewer_summary.json"
REVIEWER_PACKAGES_DIRNAME = "reviewer_packages"
CANONICAL_RESULTS_DIR = (Path(__file__).resolve().parents[1] / "results").resolve()
CANONICAL_RESULT_FILENAMES = {
    RUN_MANIFEST_FILENAME,
    EVALUATION_OUTPUT_FILENAME,
    FLAGGED_OUTPUT_FILENAME,
    SUMMARY_OUTPUT_FILENAME,
    PUBLIC_RAW_FILENAME,
}
DERIVED_NOTICE = (
    "Derived non-canonical reviewer package. This package is a convenience view built from completed-run "
    "artifacts. It does not rescore cases, change prompts, change datasets, change thresholds, or replace "
    "the canonical artifact sources of truth."
)
EVALUATION_REQUIRED_COLUMNS = {
    "case_id",
    "run_id",
    "provider",
    "model_id",
    "prompt_version",
    "overall_grade",
    "failure_tags",
}
FLAGGED_REQUIRED_FIELDS = {
    "case_id",
    "model_id",
    "prompt_version",
    "overall_grade",
    "failure_tags",
    "question",
    "provided_context",
    "gold_key_points",
    "gold_key_points_coverage",
    "answer_text",
}
MANIFEST_REQUIRED_FIELDS = {"run_id", "provider", "model_id", "prompt_version"}
OVERLAP_FIELDS = ["model_id", "prompt_version", "overall_grade", "failure_tags"]
GRADE_ORDER = ["PASS", "WARN", "FAIL"]
GRADE_PRIORITY = {"FAIL": 0, "WARN": 1, "PASS": 2}
RISK_PRIORITY = {"high": 0, "medium": 1, "low": 2}
SCORE_FIELDS = [
    "format_compliance",
    "citation_validity",
    "required_citations",
    "uncertainty_alignment",
    "gold_key_points_coverage",
    "faithfulness_proxy",
]
FLAG_FIELDS = [
    "bogus_citations",
    "hallucination_suspected",
    "unsupported_specificity_suspected",
    "unsafe_recommendation",
    "refusal_failure",
]
SUPPORTING_SCORE_FIELD_LABELS = {
    "gold_key_points_coverage": "supporting; not grade-driving",
}


@dataclass(frozen=True)
class SourceArtifactSpec:
    artifact_id: str
    filename: str
    path_attr: str
    role: str
    used_for: tuple[str, ...]
    parsed: bool
    required: bool = True


@dataclass(frozen=True)
class ReviewerReportData:
    results_dir: Path
    manifest: dict[str, Any]
    evaluation_rows: list[dict[str, str]]
    flagged_cases: list[dict[str, Any]]
    all_cases: list[dict[str, Any]]
    grade_counts: Counter[str]
    failure_tag_counts: Counter[str]
    source_artifacts: list[dict[str, Any]]


@dataclass(frozen=True)
class ReviewerPackagePaths:
    package_dir: Path
    html_path: Path
    json_path: Path


SOURCE_ARTIFACT_SPECS = (
    SourceArtifactSpec(
        artifact_id="run_manifest",
        filename=RUN_MANIFEST_FILENAME,
        path_attr="run_manifest_path",
        role="Run identity, dataset coverage, cache/live generation provenance, and case order.",
        used_for=("run metadata", "identity validation", "canonical source links"),
        parsed=True,
    ),
    SourceArtifactSpec(
        artifact_id="evaluation_output",
        filename=EVALUATION_OUTPUT_FILENAME,
        path_attr="evaluation_output_path",
        role="Full case-level structured scores, flags, tags, grades, and run metadata per row.",
        used_for=("headline counts", "score summaries", "case index", "flagged-case validation"),
        parsed=True,
    ),
    SourceArtifactSpec(
        artifact_id="flagged_cases",
        filename=FLAGGED_OUTPUT_FILENAME,
        path_attr="flagged_output_path",
        role="WARN/FAIL subset with question, context, gold key points, answer text, grade, and tags.",
        used_for=("review-first cases", "flagged-case detail sections", "overlap validation"),
        parsed=True,
    ),
    SourceArtifactSpec(
        artifact_id="summary",
        filename=SUMMARY_OUTPUT_FILENAME,
        path_attr="summary_output_path",
        role="Canonical markdown summary for reviewer orientation and cross-checking.",
        used_for=("canonical source link", "human cross-check reference"),
        parsed=False,
    ),
    SourceArtifactSpec(
        artifact_id="raw_generations",
        filename=PUBLIC_RAW_FILENAME,
        path_attr="public_raw_path",
        role="Raw prompts, model answers, response payloads, and generation metadata for audit.",
        used_for=("canonical source link", "prompt and answer audit reference"),
        parsed=False,
    ),
)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def load_evaluation_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(EVALUATION_REQUIRED_COLUMNS - fieldnames)
        if missing:
            raise ValueError(f"{path.name} missing required columns: {', '.join(missing)}")

        rows = list(reader)

    if not rows:
        raise ValueError(f"{path.name} is empty")
    return rows


def load_flagged_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path.name} line {line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Expected JSON object in {path.name} line {line_number}")
            rows.append(row)
    return rows


def parse_failure_tags(value: Any) -> list[str]:
    return [tag.strip() for tag in str(value or "").split("|") if tag.strip()]


def validate_manifest(manifest: dict[str, Any]) -> None:
    missing = sorted(
        field
        for field in MANIFEST_REQUIRED_FIELDS
        if field not in manifest or str(manifest.get(field, "")).strip() == ""
    )
    if missing:
        raise ValueError(f"run_manifest.json missing required fields: {', '.join(missing)}")


def validate_evaluation_rows(manifest: dict[str, Any], rows: list[dict[str, str]]) -> None:
    validate_manifest(manifest)

    expected_identity = {
        "run_id": str(manifest["run_id"]),
        "provider": str(manifest["provider"]),
        "model_id": str(manifest["model_id"]),
        "prompt_version": str(manifest["prompt_version"]),
    }
    seen_case_ids: set[str] = set()
    evaluation_case_ids: list[str] = []

    for row in rows:
        case_id = str(row.get("case_id", "")).strip()
        if not case_id:
            raise ValueError("evaluation_output.csv contains a row without case_id")
        if case_id in seen_case_ids:
            raise ValueError(f"evaluation_output.csv contains duplicate case_id: {case_id}")
        seen_case_ids.add(case_id)
        evaluation_case_ids.append(case_id)

        for field, expected_value in expected_identity.items():
            actual_value = str(row.get(field, ""))
            if actual_value != expected_value:
                raise ValueError(
                    f"evaluation_output.csv field {field} for {case_id} does not match run_manifest.json: "
                    f"expected {expected_value}, found {actual_value}"
                )

    manifest_case_ids = [str(case_id) for case_id in manifest.get("case_ids", [])]
    if manifest_case_ids and evaluation_case_ids != manifest_case_ids:
        raise ValueError("evaluation_output.csv case order/content does not match run_manifest.json")

    if "case_count" in manifest and len(rows) != int(manifest["case_count"]):
        raise ValueError(
            f"evaluation_output.csv row count does not match run_manifest.json: "
            f"expected {manifest['case_count']}, found {len(rows)}"
        )


def ensure_required_source_artifacts(results_dir: str | Path) -> None:
    paths = build_artifact_paths(str(results_dir))
    missing: list[Path] = []
    for spec in SOURCE_ARTIFACT_SPECS:
        path = getattr(paths, spec.path_attr)
        if spec.required and not path.exists():
            missing.append(path)

    if missing:
        missing_paths = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(
            "Missing required source artifact(s) for reviewer package: "
            f"{missing_paths}. A completed run package requires "
            f"{RUN_MANIFEST_FILENAME}, {EVALUATION_OUTPUT_FILENAME}, {FLAGGED_OUTPUT_FILENAME}, "
            f"{SUMMARY_OUTPUT_FILENAME}, and {PUBLIC_RAW_FILENAME}."
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    return str(path).replace(os.sep, "/")


def relative_link(from_dir: Path, target: Path) -> str:
    return Path(os.path.relpath(target, start=from_dir)).as_posix()


def build_source_artifacts(results_dir: Path) -> list[dict[str, Any]]:
    paths = build_artifact_paths(str(results_dir))
    artifacts: list[dict[str, Any]] = []
    for spec in SOURCE_ARTIFACT_SPECS:
        path = getattr(paths, spec.path_attr)
        present = path.exists()
        artifacts.append(
            {
                "artifact_id": spec.artifact_id,
                "filename": spec.filename,
                "source_path": display_path(path),
                "role": spec.role,
                "used_for": list(spec.used_for),
                "required": spec.required,
                "parsed": spec.parsed,
                "present": present,
                "bytes": path.stat().st_size if present else None,
                "sha256": sha256_file(path) if present else None,
            }
        )
    return artifacts


def parse_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_bool_string(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def slugify(value: Any) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())
    slug = slug.strip("-._")
    return slug or "unknown"


def case_anchor(case_id: Any) -> str:
    return f"case-{slugify(case_id)}"


def lowest_metric(scores: dict[str, Any]) -> dict[str, Any] | None:
    numeric_scores: list[tuple[float, str]] = []
    for field in SCORE_FIELDS:
        if field not in scores:
            continue
        value = parse_float(scores.get(field))
        if value is not None:
            numeric_scores.append((value, field))
    if not numeric_scores:
        return None

    value, metric = sorted(numeric_scores, key=lambda item: (item[0], item[1]))[0]
    item: dict[str, Any] = {
        "metric": metric,
        "display_name": metric_display_name(metric),
        "value": round(value, 6),
    }
    note = metric_interpretation_note(metric)
    if note:
        item["interpretation_note"] = note
    return item


def format_metric(metric: dict[str, Any] | None) -> str:
    if not metric:
        return ""
    metric_name = metric_display_name(metric.get("metric", ""))
    value = metric.get("value")
    if isinstance(value, (int, float)):
        return f"{metric_name}={value:.3f}"
    return f"{metric_name}={value}"


def metric_display_name(metric: Any) -> str:
    metric_name = str(metric or "")
    label = metric_interpretation_note(metric_name)
    if label:
        return f"{metric_name} ({label})"
    return metric_name


def metric_interpretation_note(metric: Any) -> str:
    return SUPPORTING_SCORE_FIELD_LABELS.get(str(metric or ""), "")


def build_priority_reason(case: dict[str, Any]) -> str:
    parts = [f"grade={case.get('overall_grade', '')}"]
    if case.get("risk_level"):
        parts.append(f"risk={case.get('risk_level')}")
    tags = case.get("failure_tags_list") or []
    if tags:
        parts.append(f"tags={', '.join(tags)}")
    metric = lowest_metric(case.get("scores", {}))
    if metric:
        parts.append(f"orientation metric {format_metric(metric)}")
    return "; ".join(parts)


def review_priority_key(case: dict[str, Any]) -> tuple[int, int, float, str]:
    grade = str(case.get("overall_grade", "")).upper()
    risk = str(case.get("risk_level", "")).lower()
    metric = lowest_metric(case.get("scores", {}))
    metric_value = float(metric["value"]) if metric else 1.0
    return (
        GRADE_PRIORITY.get(grade, 99),
        RISK_PRIORITY.get(risk, 99),
        metric_value,
        str(case.get("case_id", "")),
    )


def build_flagged_cases(
    evaluation_rows: list[dict[str, str]], flagged_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    evaluation_by_case = {row["case_id"]: row for row in evaluation_rows}
    seen_case_ids: set[str] = set()
    flagged_cases: list[dict[str, Any]] = []

    for index, flagged in enumerate(flagged_rows, start=1):
        missing = sorted(field for field in FLAGGED_REQUIRED_FIELDS if field not in flagged)
        label = str(flagged.get("case_id", f"line {index}"))
        if missing:
            raise ValueError(f"flagged_cases.jsonl row {label} missing required fields: {', '.join(missing)}")

        case_id = str(flagged["case_id"])
        if case_id in seen_case_ids:
            raise ValueError(f"flagged_cases.jsonl contains duplicate case_id: {case_id}")
        seen_case_ids.add(case_id)

        if case_id not in evaluation_by_case:
            raise ValueError(f"flagged_cases.jsonl case_id is not present in evaluation_output.csv: {case_id}")

        evaluation = evaluation_by_case[case_id]
        for field in OVERLAP_FIELDS:
            flagged_value = str(flagged.get(field, ""))
            evaluation_value = str(evaluation.get(field, ""))
            if flagged_value != evaluation_value:
                raise ValueError(
                    f"flagged_cases.jsonl field {field} for {case_id} does not match evaluation_output.csv: "
                    f"expected {evaluation_value}, found {flagged_value}"
                )

        grade = str(flagged.get("overall_grade", ""))
        if grade not in {"WARN", "FAIL"}:
            raise ValueError(f"flagged_cases.jsonl row {case_id} has non-flagged grade: {grade}")

        scores = {
            field: evaluation.get(field, flagged.get(field, ""))
            for field in SCORE_FIELDS
            if field in evaluation or field in flagged
        }
        flags = {field: evaluation.get(field, "") for field in FLAG_FIELDS if field in evaluation}
        failure_tags_list = parse_failure_tags(flagged.get("failure_tags", ""))
        flagged_cases.append(
            {
                "case_id": case_id,
                "detail_anchor": case_anchor(case_id),
                "run_id": evaluation.get("run_id", ""),
                "provider": evaluation.get("provider", ""),
                "model_id": flagged.get("model_id", ""),
                "prompt_version": flagged.get("prompt_version", ""),
                "source_run_id": evaluation.get("source_run_id", ""),
                "generation_mode": evaluation.get("generation_mode", ""),
                "timestamp_utc": evaluation.get("timestamp_utc", ""),
                "overall_grade": flagged.get("overall_grade", ""),
                "failure_tags": flagged.get("failure_tags", ""),
                "failure_tags_list": failure_tags_list,
                "category": evaluation.get("category", ""),
                "risk_level": evaluation.get("risk_level", ""),
                "expected_behavior": evaluation.get("expected_behavior", ""),
                "question": flagged.get("question", ""),
                "provided_context": flagged.get("provided_context", ""),
                "gold_key_points": flagged.get("gold_key_points", ""),
                "answer_text": flagged.get("answer_text", ""),
                "scores": scores,
                "flags": flags,
                "lowest_metric": lowest_metric(scores),
                "source_provenance": {
                    "run_manifest.json": [
                        "run_id",
                        "provider",
                        "model_id",
                        "prompt_version",
                        "dataset_sha256",
                        "case_ids",
                    ],
                    "evaluation_output.csv": [
                        "run_id",
                        "provider",
                        "category",
                        "risk_level",
                        "expected_behavior",
                        "overall_grade",
                        "failure_tags",
                        "metric scores",
                        "boolean flags",
                    ],
                    "flagged_cases.jsonl": [
                        "question",
                        "provided_context",
                        "gold_key_points",
                        "answer_text",
                        "overall_grade",
                        "failure_tags",
                    ],
                },
            }
        )

    ordered_cases: list[dict[str, Any]] = []
    for review_rank, case in enumerate(sorted(flagged_cases, key=review_priority_key), start=1):
        enriched = dict(case)
        enriched["review_rank"] = review_rank
        enriched["review_priority_reason"] = build_priority_reason(enriched)
        ordered_cases.append(enriched)
    return ordered_cases


def build_all_cases(
    evaluation_rows: list[dict[str, str]], flagged_cases: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    flagged_by_case = {case["case_id"]: case for case in flagged_cases}
    all_cases: list[dict[str, Any]] = []
    for row in evaluation_rows:
        case_id = row.get("case_id", "")
        scores = {field: row.get(field, "") for field in SCORE_FIELDS if field in row}
        flags = {field: row.get(field, "") for field in FLAG_FIELDS if field in row}
        flagged = flagged_by_case.get(case_id)
        all_cases.append(
            {
                "case_id": case_id,
                "detail_anchor": flagged.get("detail_anchor") if flagged else None,
                "run_id": row.get("run_id", ""),
                "provider": row.get("provider", ""),
                "model_id": row.get("model_id", ""),
                "prompt_version": row.get("prompt_version", ""),
                "source_run_id": row.get("source_run_id", ""),
                "generation_mode": row.get("generation_mode", ""),
                "timestamp_utc": row.get("timestamp_utc", ""),
                "category": row.get("category", ""),
                "risk_level": row.get("risk_level", ""),
                "expected_behavior": row.get("expected_behavior", ""),
                "overall_grade": row.get("overall_grade", ""),
                "failure_tags": row.get("failure_tags", ""),
                "failure_tags_list": parse_failure_tags(row.get("failure_tags", "")),
                "scores": scores,
                "flags": flags,
                "lowest_metric": lowest_metric(scores),
                "has_flagged_detail": flagged is not None,
                "source_provenance": {
                    "evaluation_output.csv": [
                        "case_id",
                        "run_id",
                        "provider",
                        "model_id",
                        "prompt_version",
                        "category",
                        "risk_level",
                        "expected_behavior",
                        "overall_grade",
                        "failure_tags",
                        "metric scores",
                        "boolean flags",
                    ]
                },
            }
        )
    return all_cases


def load_report_data(results_dir: str = "results") -> ReviewerReportData:
    results_path = Path(results_dir)
    ensure_required_source_artifacts(results_path)
    paths = build_artifact_paths(str(results_path))
    manifest = load_json(paths.run_manifest_path)
    evaluation_rows = load_evaluation_rows(paths.evaluation_output_path)
    flagged_rows = load_flagged_rows(paths.flagged_output_path)

    validate_evaluation_rows(manifest, evaluation_rows)
    flagged_cases = build_flagged_cases(evaluation_rows, flagged_rows)
    all_cases = build_all_cases(evaluation_rows, flagged_cases)

    grade_counts: Counter[str] = Counter(row.get("overall_grade", "") or "(blank)" for row in evaluation_rows)
    failure_tag_counts: Counter[str] = Counter(
        tag for row in evaluation_rows for tag in parse_failure_tags(row.get("failure_tags", ""))
    )

    return ReviewerReportData(
        results_dir=results_path,
        manifest=manifest,
        evaluation_rows=evaluation_rows,
        flagged_cases=flagged_cases,
        all_cases=all_cases,
        grade_counts=grade_counts,
        failure_tag_counts=failure_tag_counts,
        source_artifacts=build_source_artifacts(results_path),
    )


def ordered_grades(grade_counts: Counter[str]) -> list[str]:
    extras = sorted(grade for grade in grade_counts if grade not in GRADE_ORDER)
    return GRADE_ORDER + extras


def build_grade_distribution(grade_counts: Counter[str], total: int) -> list[dict[str, Any]]:
    distribution = []
    for grade in ordered_grades(grade_counts):
        count = grade_counts.get(grade, 0)
        distribution.append(
            {
                "grade": grade,
                "count": count,
                "share": round((count / total) if total else 0.0, 6),
            }
        )
    return distribution


def build_metric_summary(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for field in SCORE_FIELDS:
        values = [value for row in rows if (value := parse_float(row.get(field))) is not None]
        if not values:
            continue
        item: dict[str, Any] = {
            "metric": field,
            "display_name": metric_display_name(field),
            "count": len(values),
            "mean": round(sum(values) / len(values), 6),
            "min": round(min(values), 6),
            "max": round(max(values), 6),
        }
        note = metric_interpretation_note(field)
        if note:
            item["interpretation_note"] = note
        summaries.append(item)
    return summaries


def build_flag_counts(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    total = len(rows)
    counts: list[dict[str, Any]] = []
    for field in FLAG_FIELDS:
        if not any(field in row for row in rows):
            continue
        true_count = sum(1 for row in rows if parse_bool_string(row.get(field, "")))
        counts.append(
            {
                "flag": field,
                "true_count": true_count,
                "share": round((true_count / total) if total else 0.0, 6),
            }
        )
    return counts


def build_breakdown(rows: list[dict[str, str]], field: str, grades: list[str]) -> list[dict[str, Any]]:
    counters: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        value = row.get(field, "") or "(blank)"
        counters[value][row.get("overall_grade", "") or "(blank)"] += 1

    breakdown = []
    for value in sorted(counters):
        grade_counts = counters[value]
        total = sum(grade_counts.values())
        breakdown.append(
            {
                field: value,
                "total": total,
                "grades": {grade: grade_counts.get(grade, 0) for grade in grades},
            }
        )
    return breakdown


def build_failure_tag_counts(failure_tag_counts: Counter[str]) -> list[dict[str, Any]]:
    return [
        {"failure_tag": tag, "count": count}
        for tag, count in sorted(failure_tag_counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def enrich_source_artifacts_for_package(
    source_artifacts: list[dict[str, Any]], package_dir: Path
) -> list[dict[str, Any]]:
    enriched = []
    for artifact in source_artifacts:
        source_path = Path(str(artifact["source_path"]))
        item = dict(artifact)
        item["relative_link_from_package"] = relative_link(package_dir, source_path) if item["present"] else None
        enriched.append(item)
    return enriched


def build_reviewer_summary(data: ReviewerReportData, package_dir: Path) -> dict[str, Any]:
    total_cases = len(data.evaluation_rows)
    grades = ordered_grades(data.grade_counts)
    flagged_count = len(data.flagged_cases)

    review_first_cases = [
        {
            "rank": case.get("review_rank"),
            "case_id": case.get("case_id"),
            "detail_anchor": case.get("detail_anchor"),
            "overall_grade": case.get("overall_grade"),
            "category": case.get("category"),
            "risk_level": case.get("risk_level"),
            "expected_behavior": case.get("expected_behavior"),
            "failure_tags": case.get("failure_tags_list", []),
            "lowest_metric": case.get("lowest_metric"),
            "priority_reason": case.get("review_priority_reason"),
            "source_refs": ["evaluation_output.csv", "flagged_cases.jsonl"],
        }
        for case in data.flagged_cases
    ]

    run_identity = {
        "provider": data.manifest.get("provider", ""),
        "model_id": data.manifest.get("model_id", ""),
        "run_id": data.manifest.get("run_id", ""),
        "prompt_version": data.manifest.get("prompt_version", ""),
        "run_kind": data.manifest.get("run_kind", ""),
        "benchmark_status": data.manifest.get("benchmark_status", ""),
        "case_count": data.manifest.get("case_count", total_cases),
        "dataset_total_rows": data.manifest.get("dataset_total_rows", ""),
        "is_full_dataset_run": data.manifest.get("is_full_dataset_run", ""),
        "dataset_path": data.manifest.get("dataset_path", ""),
        "dataset_sha256": data.manifest.get("dataset_sha256", ""),
        "generation_modes": data.manifest.get("generation_modes", {}),
        "source_run_ids": data.manifest.get("source_run_ids", []),
        "cache_hits": data.manifest.get("cache_hits", ""),
        "live_generations": data.manifest.get("live_generations", ""),
    }

    return {
        "package": {
            "schema_version": REVIEWER_PACKAGE_SCHEMA_VERSION,
            "derived_non_canonical": True,
            "disclaimer": DERIVED_NOTICE,
            "source_run_directory": display_path(data.results_dir),
            "html_report": REVIEWER_REPORT_FILENAME,
            "json_summary": REVIEWER_SUMMARY_FILENAME,
        },
        "validation": {
            "status": "passed",
            "checks": [
                "Required completed-run source artifacts are present.",
                "evaluation_output.csv run identity matches run_manifest.json.",
                "evaluation_output.csv case order/content matches run_manifest.json when manifest case_ids are present.",
                "flagged_cases.jsonl case IDs are a subset of evaluation_output.csv.",
                "flagged_cases.jsonl overlap fields match evaluation_output.csv.",
                "flagged_cases.jsonl contains only WARN/FAIL rows.",
            ],
            "non_canonical_boundary": (
                "This package is read-only derived tooling. Canonical scoring and artifact semantics remain in the "
                "source artifacts listed below."
            ),
        },
        "source_artifacts": enrich_source_artifacts_for_package(data.source_artifacts, package_dir),
        "run_identity": run_identity,
        "headline_results": {
            "total_cases": total_cases,
            "flagged_cases": flagged_count,
            "pass": data.grade_counts.get("PASS", 0),
            "warn": data.grade_counts.get("WARN", 0),
            "fail": data.grade_counts.get("FAIL", 0),
            "cases_with_failure_tags": sum(1 for row in data.evaluation_rows if row.get("failure_tags", "").strip()),
        },
        "grade_distribution": build_grade_distribution(data.grade_counts, total_cases),
        "metric_summary": build_metric_summary(data.evaluation_rows),
        "boolean_flag_counts": build_flag_counts(data.evaluation_rows),
        "category_breakdown": build_breakdown(data.evaluation_rows, "category", grades),
        "risk_breakdown": build_breakdown(data.evaluation_rows, "risk_level", grades),
        "failure_tag_counts": build_failure_tag_counts(data.failure_tag_counts),
        "review_first_cases": review_first_cases,
        "all_cases": data.all_cases,
        "flagged_case_details": data.flagged_cases,
        "canonical_source_guidance": {
            "run_identity": RUN_MANIFEST_FILENAME,
            "full_scored_table": EVALUATION_OUTPUT_FILENAME,
            "flagged_case_text": FLAGGED_OUTPUT_FILENAME,
            "top_level_markdown_summary": SUMMARY_OUTPUT_FILENAME,
            "raw_prompt_answer_audit": PUBLIC_RAW_FILENAME,
        },
    }


def esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def display_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{key}: {val}" for key, val in value.items())
    return str(value if value is not None else "")


def render_definition_list(items: list[tuple[str, Any]]) -> str:
    parts = ['<dl class="kv-list">']
    for label, value in items:
        parts.append(f"<dt>{esc(label)}</dt><dd>{esc(display_value(value))}</dd>")
    parts.append("</dl>")
    return "".join(parts)


def grade_class(grade: Any) -> str:
    normalized = str(grade).strip().lower()
    if normalized in {"pass", "warn", "fail"}:
        return normalized
    return "other"


def percent(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 100:.1f}%"
    return ""


def number(value: Any, digits: int = 3) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return esc(value)


def render_source_artifacts(summary: dict[str, Any]) -> str:
    rows = []
    for artifact in summary["source_artifacts"]:
        link = artifact.get("relative_link_from_package") or artifact.get("source_path", "")
        sha = str(artifact.get("sha256") or "")
        parsed = "parsed" if artifact.get("parsed") else "linked"
        rows.append(
            "<tr>"
            f"<th scope=\"row\"><a href=\"{esc(link)}\">{esc(artifact.get('filename', ''))}</a></th>"
            f"<td>{esc(artifact.get('role', ''))}</td>"
            f"<td>{esc(parsed)}</td>"
            f"<td>{esc(artifact.get('bytes', ''))}</td>"
            f"<td><code>{esc(sha[:12])}</code></td>"
            "</tr>"
        )
    return (
        "<table>"
        "<thead><tr><th>Artifact</th><th>Reviewer-package role</th><th>Use</th><th>Bytes</th>"
        "<th>SHA-256 prefix</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_headline_cards(summary: dict[str, Any]) -> str:
    headline = summary["headline_results"]
    cards = [
        ("Total cases", headline.get("total_cases", 0)),
        ("Flagged cases", headline.get("flagged_cases", 0)),
        ("PASS", headline.get("pass", 0)),
        ("WARN", headline.get("warn", 0)),
        ("FAIL", headline.get("fail", 0)),
        ("Cases with tags", headline.get("cases_with_failure_tags", 0)),
    ]
    return '<div class="stats">' + "".join(
        f"<div class=\"stat\"><span>{esc(label)}</span><strong>{esc(value)}</strong></div>" for label, value in cards
    ) + "</div>"


def render_grade_distribution(summary: dict[str, Any]) -> str:
    rows = [
        f"<tr><th scope=\"row\"><span class=\"badge {grade_class(item['grade'])}\">{esc(item['grade'])}</span></th>"
        f"<td>{item['count']}</td><td>{percent(item['share'])}</td></tr>"
        for item in summary["grade_distribution"]
    ]
    return (
        "<table><thead><tr><th>Grade</th><th>Cases</th><th>Share</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_metric_summary(summary: dict[str, Any]) -> str:
    rows = []
    for item in summary["metric_summary"]:
        rows.append(
            "<tr>"
            f"<th scope=\"row\"><code>{esc(item.get('display_name') or metric_display_name(item['metric']))}</code></th>"
            f"<td>{number(item.get('mean'))}</td>"
            f"<td>{number(item.get('min'))}</td>"
            f"<td>{number(item.get('max'))}</td>"
            f"<td>{esc(item.get('count', ''))}</td>"
            "</tr>"
        )
    return (
        '<p class="muted">Metric summaries are reviewer orientation only. '
        '<code>gold_key_points_coverage</code> is a supporting checklist-style metric and is not '
        'grade-driving by itself.</p>'
        "<table><thead><tr><th>Metric</th><th>Mean</th><th>Min</th><th>Max</th><th>Rows</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_boolean_flag_counts(summary: dict[str, Any]) -> str:
    rows = []
    for item in summary["boolean_flag_counts"]:
        rows.append(
            "<tr>"
            f"<th scope=\"row\"><code>{esc(item['flag'])}</code></th>"
            f"<td>{esc(item.get('true_count', 0))}</td>"
            f"<td>{percent(item.get('share'))}</td>"
            "</tr>"
        )
    if not rows:
        return '<p class="muted">No boolean flag columns were available in evaluation_output.csv.</p>'
    return (
        "<table><thead><tr><th>Flag</th><th>True count</th><th>Share</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_breakdown_table(rows_data: list[dict[str, Any]], value_key: str, grades: list[str]) -> str:
    header = "".join(f"<th>{esc(grade)}</th>" for grade in grades)
    rows = []
    for item in rows_data:
        grade_cells = "".join(f"<td>{esc(item.get('grades', {}).get(grade, 0))}</td>" for grade in grades)
        rows.append(
            "<tr>"
            f"<th scope=\"row\">{esc(item.get(value_key, ''))}</th>"
            f"<td>{esc(item.get('total', 0))}</td>"
            f"{grade_cells}</tr>"
        )
    return (
        f"<table><thead><tr><th>{esc(value_key)}</th><th>Total</th>{header}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_failure_tag_counts(summary: dict[str, Any]) -> str:
    if not summary["failure_tag_counts"]:
        return '<p class="muted">No failure tags were present in evaluation_output.csv.</p>'
    rows = [
        f"<tr><th scope=\"row\"><code>{esc(item['failure_tag'])}</code></th><td>{esc(item['count'])}</td></tr>"
        for item in summary["failure_tag_counts"]
    ]
    return (
        "<table><thead><tr><th>Failure tag</th><th>Cases</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_review_first(summary: dict[str, Any]) -> str:
    cases = summary["review_first_cases"]
    if not cases:
        return '<p class="muted">No WARN or FAIL cases were present in flagged_cases.jsonl.</p>'

    rows = []
    for case in cases:
        metric = format_metric(case.get("lowest_metric"))
        tags = ", ".join(case.get("failure_tags") or [])
        rows.append(
            "<tr>"
            f"<td>{esc(case.get('rank', ''))}</td>"
            f"<th scope=\"row\"><a href=\"#{esc(case.get('detail_anchor', ''))}\">{esc(case.get('case_id', ''))}</a></th>"
            f"<td><span class=\"badge {grade_class(case.get('overall_grade'))}\">{esc(case.get('overall_grade', ''))}</span></td>"
            f"<td>{esc(case.get('category', ''))}</td>"
            f"<td>{esc(case.get('risk_level', ''))}</td>"
            f"<td>{esc(tags)}</td>"
            f"<td>{esc(metric)}</td>"
            f"<td>{esc(case.get('priority_reason', ''))}</td>"
            "</tr>"
        )
    return (
        '<p class="muted">Review order is convenience-only: it is not a severity label, benchmark score, '
        'or grade-driving rule. The metric column is an orientation aid; supporting metrics such as '
        '<code>gold_key_points_coverage</code> do not create or change grades.</p>'
        "<table><thead><tr><th>Rank</th><th>Case</th><th>Grade</th><th>Category</th><th>Risk</th>"
        "<th>Failure tags</th><th>Orientation metric</th><th>Reason</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_case_index(summary: dict[str, Any]) -> str:
    rows = []
    for case in summary["all_cases"]:
        case_id = esc(case.get("case_id", ""))
        if case.get("detail_anchor"):
            case_link = f"<a href=\"#{esc(case.get('detail_anchor'))}\">{case_id}</a>"
        else:
            case_link = case_id
        rows.append(
            "<tr>"
            f"<th scope=\"row\">{case_link}</th>"
            f"<td><span class=\"badge {grade_class(case.get('overall_grade'))}\">{esc(case.get('overall_grade', ''))}</span></td>"
            f"<td>{esc(case.get('category', ''))}</td>"
            f"<td>{esc(case.get('risk_level', ''))}</td>"
            f"<td>{esc(case.get('expected_behavior', ''))}</td>"
            f"<td>{esc(', '.join(case.get('failure_tags_list') or []))}</td>"
            f"<td>{esc(format_metric(case.get('lowest_metric')))}</td>"
            f"<td>{'yes' if case.get('has_flagged_detail') else 'no'}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Case</th><th>Grade</th><th>Category</th><th>Risk</th>"
        "<th>Expected behavior</th><th>Failure tags</th><th>Orientation metric</th>"
        "<th>Flagged detail</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_scores_or_flags(items: dict[str, Any], label: str) -> str:
    if not items:
        return f'<p class="muted">No {esc(label)} fields were available.</p>'
    if label == "score":
        return render_definition_list([(metric_display_name(field), value) for field, value in items.items()])
    return render_definition_list([(field, value) for field, value in items.items()])


def render_text_block(title: str, value: Any) -> str:
    return f'<section class="text-block"><h4>{esc(title)}</h4><pre>{esc(display_value(value))}</pre></section>'


def render_flagged_case_details(summary: dict[str, Any]) -> str:
    cases = summary["flagged_case_details"]
    if not cases:
        return '<p class="muted">No flagged case detail sections were generated.</p>'

    panels = []
    for case in cases:
        overlap_items = [
            ("Review rank", case.get("review_rank", "")),
            ("Model ID", case.get("model_id", "")),
            ("Prompt version", case.get("prompt_version", "")),
            ("Overall grade", case.get("overall_grade", "")),
            ("Failure tags", case.get("failure_tags", "")),
        ]
        context_items = [
            ("Run ID", case.get("run_id", "")),
            ("Provider", case.get("provider", "")),
            ("Source run ID", case.get("source_run_id", "")),
            ("Generation mode", case.get("generation_mode", "")),
            ("Category", case.get("category", "")),
            ("Risk level", case.get("risk_level", "")),
            ("Expected behavior", case.get("expected_behavior", "")),
        ]
        blocks = [
            render_text_block("Question", case.get("question", "")),
            render_text_block("Provided Context", case.get("provided_context", "")),
            render_text_block("Gold Key Points", case.get("gold_key_points", "")),
            render_text_block("Model Answer", case.get("answer_text", "")),
        ]
        panels.append(
            f"<article class=\"case-detail\" id=\"{esc(case.get('detail_anchor', ''))}\">"
            f"<h3>{esc(case.get('case_id', ''))}</h3>"
            '<p class="muted">Case detail is assembled from flagged_cases.jsonl plus validated '
            "evaluation_output.csv overlap fields. Source provenance is listed in reviewer_summary.json.</p>"
            '<div class="detail-grid">'
            "<section><h4>Validated Artifact Overlap</h4>"
            f"{render_definition_list(overlap_items)}</section>"
            "<section><h4>Run And Case Context</h4>"
            f"{render_definition_list(context_items)}</section>"
            "<section><h4>Metric Scores</h4>"
            f"{render_scores_or_flags(case.get('scores', {}), 'score')}</section>"
            "<section><h4>Boolean Flags</h4>"
            f"{render_scores_or_flags(case.get('flags', {}), 'flag')}</section>"
            "</div>"
            f"{''.join(blocks)}"
            '<p><a href="#review-first">Back to review-first list</a></p>'
            "</article>"
        )
    return "".join(panels)


def render_report_html(summary: dict[str, Any]) -> str:
    run_identity = summary["run_identity"]
    grades = [item["grade"] for item in summary["grade_distribution"]]
    run_title = (
        f"{run_identity.get('provider', '')} / {run_identity.get('model_id', '')} / "
        f"{run_identity.get('run_id', '')}"
    )
    summary_items = [
        ("Provider", run_identity.get("provider", "")),
        ("Model", run_identity.get("model_id", "")),
        ("Run ID", run_identity.get("run_id", "")),
        ("Prompt version", run_identity.get("prompt_version", "")),
        ("Run kind", run_identity.get("run_kind", "")),
        ("Benchmark status", run_identity.get("benchmark_status", "")),
        ("Cases in run", run_identity.get("case_count", "")),
        ("Dataset total rows", run_identity.get("dataset_total_rows", "")),
        ("Full dataset run", run_identity.get("is_full_dataset_run", "")),
        ("Dataset path", run_identity.get("dataset_path", "")),
        ("Dataset SHA-256", run_identity.get("dataset_sha256", "")),
        ("Generation modes", run_identity.get("generation_modes", "")),
        ("Source run IDs", run_identity.get("source_run_ids", "")),
        ("Cache hits", run_identity.get("cache_hits", "")),
        ("Live generations", run_identity.get("live_generations", "")),
    ]

    css = """
body {
  margin: 0;
  background: #f7f7f7;
  color: #202124;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.45;
}
header {
  background: #ffffff;
  border-bottom: 1px solid #d8d8d8;
  padding: 24px;
}
main {
  max-width: 1240px;
  margin: 0 auto;
  padding: 24px;
}
h1, h2, h3, h4 {
  margin: 0 0 12px;
}
p {
  margin: 0 0 12px;
}
a {
  color: #174ea6;
}
.notice {
  background: #fff7d1;
  border: 1px solid #d6b84a;
  border-radius: 6px;
  margin-top: 14px;
  padding: 12px;
}
.panel {
  background: #ffffff;
  border: 1px solid #d8d8d8;
  border-radius: 6px;
  margin-bottom: 20px;
  padding: 18px;
}
.toc {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 16px 0 0;
  padding: 0;
}
.toc li {
  list-style: none;
}
.toc a {
  background: #f1f3f4;
  border: 1px solid #d8d8d8;
  border-radius: 6px;
  display: inline-block;
  padding: 6px 9px;
  text-decoration: none;
}
.stats {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  margin-bottom: 20px;
}
.stat {
  background: #ffffff;
  border: 1px solid #d8d8d8;
  border-radius: 6px;
  padding: 14px;
}
.stat strong {
  display: block;
  font-size: 1.6rem;
}
.muted {
  color: #5f6368;
}
table {
  border-collapse: collapse;
  width: 100%;
}
th, td {
  border-bottom: 1px solid #e4e4e4;
  padding: 9px 10px;
  text-align: left;
  vertical-align: top;
}
thead th {
  background: #eeeeee;
  font-weight: 700;
}
.table-wrap {
  overflow-x: auto;
}
.two-col {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}
.kv-list {
  display: grid;
  grid-template-columns: minmax(130px, 230px) 1fr;
  gap: 6px 12px;
  margin: 0;
}
.kv-list dt {
  color: #5f6368;
  font-weight: 700;
}
.kv-list dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.badge {
  border-radius: 6px;
  display: inline-block;
  font-weight: 700;
  padding: 2px 8px;
}
.badge.pass {
  background: #d8f5d0;
}
.badge.warn {
  background: #ffe8a3;
}
.badge.fail {
  background: #ffc9c9;
}
.badge.other {
  background: #e5e5e5;
}
.case-detail {
  border-top: 3px solid #d8d8d8;
  margin-top: 22px;
  padding-top: 18px;
}
.detail-grid {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
}
.text-block {
  margin-top: 14px;
}
pre {
  background: #f2f2f2;
  border: 1px solid #dedede;
  border-radius: 6px;
  margin: 0;
  overflow-x: auto;
  padding: 12px;
  white-space: pre-wrap;
}
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
@media (max-width: 760px) {
  main {
    padding: 16px;
  }
  .kv-list {
    grid-template-columns: 1fr;
  }
}
@media print {
  body {
    background: #ffffff;
  }
  header, .panel, .stat {
    border-color: #999999;
  }
  a {
    color: #000000;
  }
}
"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Clinical AI Evaluation Reviewer Package</title>
  <style>{css}</style>
</head>
<body>
  <header>
    <h1>Clinical AI Evaluation Reviewer Package</h1>
    <p><strong>{esc(run_title)}</strong></p>
    <div class="notice"><strong>Derived / non-canonical:</strong> {esc(summary["package"]["disclaimer"])}</div>
    <ul class="toc" aria-label="Table of contents">
      <li><a href="#run">Run</a></li>
      <li><a href="#sources">Sources</a></li>
      <li><a href="#results">Results</a></li>
      <li><a href="#failure-summary">Failure Summary</a></li>
      <li><a href="#review-first">Review First</a></li>
      <li><a href="#case-index">Case Index</a></li>
      <li><a href="#flagged-details">Flagged Details</a></li>
      <li><a href="#canonical">Canonical Sources</a></li>
    </ul>
  </header>
  <main>
    {render_headline_cards(summary)}
    <section class="panel" id="run">
      <h2>Run Summary</h2>
      {render_definition_list(summary_items)}
    </section>
    <section class="panel" id="sources">
      <h2>Source Artifacts</h2>
      <p class="muted">The package validates and reads completed-run artifacts, then links back to the canonical files for audit.</p>
      <div class="table-wrap">{render_source_artifacts(summary)}</div>
    </section>
    <section class="panel" id="results">
      <h2>Overall Results</h2>
      <div class="two-col">
        <section>
          <h3>Grade Distribution</h3>
          {render_grade_distribution(summary)}
        </section>
        <section>
          <h3>Metric Score Summary</h3>
          {render_metric_summary(summary)}
        </section>
      </div>
    </section>
    <section class="panel" id="failure-summary">
      <h2>Failure Categories And Flags</h2>
      <div class="two-col">
        <section>
          <h3>Failure Tag Counts</h3>
          {render_failure_tag_counts(summary)}
        </section>
        <section>
          <h3>Boolean Flag Counts</h3>
          {render_boolean_flag_counts(summary)}
        </section>
      </div>
      <div class="two-col">
        <section>
          <h3>Category Breakdown</h3>
          {render_breakdown_table(summary["category_breakdown"], "category", grades)}
        </section>
        <section>
          <h3>Risk Breakdown</h3>
          {render_breakdown_table(summary["risk_breakdown"], "risk_level", grades)}
        </section>
      </div>
    </section>
    <section class="panel" id="review-first">
      <h2>Review First</h2>
      <div class="table-wrap">{render_review_first(summary)}</div>
    </section>
    <section class="panel" id="case-index">
      <h2>Full Case Index</h2>
      <p class="muted">This index is derived from evaluation_output.csv. Only WARN/FAIL cases have answer/context detail sections because that text is supplied by flagged_cases.jsonl.</p>
      <div class="table-wrap">{render_case_index(summary)}</div>
    </section>
    <section class="panel" id="flagged-details">
      <h2>Flagged Case Details</h2>
      {render_flagged_case_details(summary)}
    </section>
    <section class="panel" id="canonical">
      <h2>Canonical Sources Of Truth</h2>
      <p>Use this report to navigate. Use the source artifacts to adjudicate the run.</p>
      {render_definition_list([
        ("Run identity", summary["canonical_source_guidance"]["run_identity"]),
        ("Full scored table", summary["canonical_source_guidance"]["full_scored_table"]),
        ("Flagged case text", summary["canonical_source_guidance"]["flagged_case_text"]),
        ("Markdown summary", summary["canonical_source_guidance"]["top_level_markdown_summary"]),
        ("Raw prompt/answer audit", summary["canonical_source_guidance"]["raw_prompt_answer_audit"]),
      ])}
    </section>
  </main>
</body>
</html>
"""


def render_summary_json(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, ensure_ascii=True) + "\n"


def default_package_dir(results_dir: str | Path, manifest: dict[str, Any]) -> Path:
    results_path = Path(results_dir)
    identity = "_".join(
        slugify(manifest.get(field, ""))
        for field in ("provider", "model_id", "run_id")
        if str(manifest.get(field, "")).strip()
    )
    identity = identity or "run"
    return results_path.parent / REVIEWER_PACKAGES_DIRNAME / identity


def validate_custom_output_path(html_output_path: str) -> None:
    output_path = Path(html_output_path).resolve()
    canonical_paths = {
        (CANONICAL_RESULTS_DIR / filename).resolve()
        for filename in CANONICAL_RESULT_FILENAMES
    }
    if output_path in canonical_paths:
        raise ValueError(f"Reviewer output cannot overwrite canonical artifact: {output_path}")


def write_reviewer_package(
    results_dir: str = "results",
    output_dir: str | None = None,
    html_output_path: str | None = None,
) -> ReviewerPackagePaths:
    if html_output_path:
        validate_custom_output_path(html_output_path)
    data = load_report_data(results_dir)
    if html_output_path:
        html_path = Path(html_output_path)
        package_dir = html_path.parent
    else:
        package_dir = Path(output_dir) if output_dir else default_package_dir(results_dir, data.manifest)
        html_path = package_dir / REVIEWER_REPORT_FILENAME
    json_path = package_dir / REVIEWER_SUMMARY_FILENAME

    summary = build_reviewer_summary(data, package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(render_summary_json(summary), encoding="utf-8")
    html_path.write_text(render_report_html(summary), encoding="utf-8")
    return ReviewerPackagePaths(package_dir=package_dir, html_path=html_path, json_path=json_path)


def main(
    results_dir: str = "results",
    output_dir: str | None = None,
    output_path: str | None = None,
) -> ReviewerPackagePaths:
    paths = write_reviewer_package(
        results_dir=results_dir,
        output_dir=output_dir,
        html_output_path=output_path,
    )
    print("Wrote reviewer package:")
    print(f"  HTML: {paths.html_path}")
    print(f"  JSON: {paths.json_path}")
    return paths


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Build a derived, non-canonical reviewer package from completed evaluation artifacts."
    )
    parser.add_argument("--results-dir", default="results", help="Directory containing completed-run artifacts.")
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Directory for reviewer_report.html and reviewer_summary.json. Defaults to a run-specific directory "
            f"under {REVIEWER_PACKAGES_DIRNAME}/ beside --results-dir."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Legacy/custom HTML output path. JSON is written beside it. Prefer --output-dir for reviewer packages."
        ),
    )
    args = parser.parse_args()

    main(results_dir=args.results_dir, output_dir=args.output_dir, output_path=args.output)


if __name__ == "__main__":
    cli()
