# Reviewer Package

> v0.2.0 integrity boundary: `evaluation_manifest.json` is required. It binds the
> scored raw text, run manifest, evaluation CSV, complete flagged subset, evaluator
> code, and executed blocking acceptance result; summary adds its own hash.
> Summary/reviewer commands reject stale or unscored files and require the readable
> dataset named in the manifest. Re-run evaluation and then summary after changes.
> Legacy artifacts require an explicit re-score; the historical audit bundle is
> preserved under `audits/adversarial_2026_09_04/baseline/`.
> This is a consistency receipt, not a signed attestation or clinical safety evidence.


The reviewer package is a derived, non-canonical convenience layer for inspecting one completed evaluation run.

It is designed to make human review faster without changing benchmark semantics. It reads completed-run artifacts, validates run identity and flagged-case overlap, then writes a local HTML report and machine-readable JSON summary.

## What It Is

The package contains:

- `reviewer_report.html`: a self-contained local HTML report for one run.
- `reviewer_summary.json`: a structured derived summary that mirrors the HTML sections.

The HTML report includes:

- run identity and provenance from `run_manifest.json`
- source artifact links, sizes, and SHA-256 hashes
- headline PASS / WARN / FAIL counts from `evaluation_output.csv`
- metric score summaries derived from existing score columns
- failure tag and boolean flag summaries derived from existing fields
- category and risk breakdowns derived from existing fields
- a review-first list for WARN/FAIL cases
- a full case index
- per-flagged-case detail sections using the text available in `flagged_cases.jsonl`

The JSON file carries the same major sections for future tooling.

## What It Is Not

The reviewer package is not a canonical benchmark artifact.

It does not:

- rescore cases
- change prompts
- change datasets
- change thresholds
- change metrics or failure tag definitions
- replace `evaluation_output.csv`, `flagged_cases.jsonl`, `summary.md`, or `raw_generations.jsonl`
- provide clinician adjudication or proof of clinical safety

If the package and canonical artifacts disagree, treat the canonical artifacts as the source of truth and regenerate the package.

## Required Source Artifacts

The generator expects a completed run directory containing:

- `run_manifest.json`
- `evaluation_output.csv`
- `flagged_cases.jsonl`
- `summary.md`
- `raw_generations.jsonl`

The generator parses the manifest, evaluation CSV, and flagged-case JSONL. It links to `summary.md` and `raw_generations.jsonl` for reviewer cross-checking and prompt/answer audit.

Before writing output, it verifies:

- required source artifacts are present
- evaluation row run identity matches `run_manifest.json`
- evaluation row count and case order match the manifest when manifest case IDs are present
- flagged cases are a subset of evaluated cases
- overlapping flagged-case fields match the evaluation CSV
- flagged-case rows are WARN or FAIL

## Generate The Package

From the repo root:

```bash
make reviewer-package
```

Equivalent direct command:

```bash
python src/build_reviewer_report.py --results-dir results
```

By default, the package is written outside the canonical `results/` directory:

```text
reviewer_packages/<provider>_<model_id>_<run_id>/
├── reviewer_report.html
└── reviewer_summary.json
```

For a custom output directory:

```bash
python src/build_reviewer_report.py --results-dir results --output-dir /tmp/clinical-reviewer-package
```

Open `reviewer_report.html` in a browser. No network access or frontend build step is required.

## Review-First Ordering

The review-first list is a convenience ordering only. It uses existing fields:

- `overall_grade`
- `risk_level`
- `failure_tags`
- an orientation metric value selected from existing metric score fields for sorting only

This ordering is not a new score, not a severity label, and not benchmark logic. It exists only to help a human reviewer decide where to start reading.

`gold_key_points_coverage` is a supporting checklist-style metric and is not grade-driving by itself. The JSON summary preserves raw source field names for auditability and adds display labels or interpretation notes where applicable; those labels are derived reviewer guidance, not scoring rules.

## Boundary Notes

The package is ignored by git through `reviewer_packages/`. Do not check generated reviewer packages into canonical `results/`.

Safe future extensions should stay read-only and derived. Examples:

- adding new sections based on existing artifact fields
- improving HTML navigation or print styling
- adding new JSON sections that expose already-existing data
- adding validation that detects artifact inconsistency without changing scoring behavior

Unsafe changes require explicit benchmark-revision intent. Examples:

- changing score thresholds
- changing failure tag meaning
- changing prompt wording
- changing dataset rows or labels
- writing back into checked-in benchmark artifacts
