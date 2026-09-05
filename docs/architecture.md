# Clinical AI Evaluation Sandbox Architecture

> v0.2.0 integrity boundary: `evaluation_manifest.json` is required. It binds the
> scored raw text, run manifest, evaluation CSV, complete flagged subset, evaluator
> code, and executed blocking acceptance result; summary adds its own hash.
> Summary/reviewer commands reject stale or unscored files and require the readable
> dataset named in the manifest. Re-run evaluation and then summary after changes.
> Legacy artifacts require an explicit re-score; the historical audit bundle is
> preserved under `audits/adversarial_2026_09_04/baseline/`.
> This is a consistency receipt, not a signed attestation or clinical safety evidence.


## Purpose

This document explains how the Clinical AI Evaluation Sandbox is structured and how data moves through the evaluation pipeline.

It is an explanatory document, not a benchmark-defining artifact. For maintenance boundaries, see `docs/maintenance_boundaries.md`.

Read this file if you want the system map: dataset, prompt, generation, evaluation, reporting, and where each artifact comes from.

## At A Glance

The sandbox simulates how a healthcare organization might evaluate an LLM before integrating it into clinical decision-support workflows.

It focuses on:

- faithfulness to provided clinical context
- citation accuracy
- uncertainty calibration
- clinical safety risks

The system is intentionally lightweight and organized around a simple automated evaluation pipeline.

## Pipeline Overview

### Stages

1. Dataset
2. Prompt construction
3. LLM generation
4. Evaluation
5. Result storage
6. Summary reporting

### Data flow

```text
dataset/clinical_questions.csv
-> src/prompt_templates.py
-> src/generate_answers.py
-> results/raw_generations.jsonl + results/run_manifest.json
-> src/run_evaluation.py + src/metrics.py
-> results/evaluation_output.csv + results/flagged_cases.jsonl
-> src/summarize_results.py
-> results/summary.md
-> src/build_reviewer_report.py
-> reviewer_packages/.../reviewer_report.html + reviewer_summary.json

Reusable raw-generation cache is stored separately at:
results/cache/raw_generations_cache.jsonl
```

## Module Breakdown

### 1. Dataset layer

Location: `dataset/clinical_questions.csv`

The dataset contains structured clinical evaluation cases designed to probe model behavior under different clinical risk scenarios.

Each row may include:

- `case_id`: unique identifier
- `category`: scenario type such as ICU triage, medication, guideline, or diagnosis
- `risk_level`: low / medium / high
- `question`: clinical decision-support question
- `provided_context`: evidence snippet the model must use
- `expected_behavior`: `answer` / `uncertain` / `refuse`
- `required_citations`: anchors that must appear, pipe-separated
- `forbidden_actions`: unsafe actions to detect, pipe-separated
- `gold_key_points`: optional checklist, pipe-separated
- `notes`: optional

Purpose: a small golden set that is stable, reviewable, and suitable for regression testing.

### 2. Prompt construction layer

Location: `src/prompt_templates.py`

Prompts enforce a strict response format so automated evaluation can parse reliably.

Required response sections:

- Recommendation
- Rationale
- Uncertainty & Escalation
- Do-not-do

Design intent:

- reduce ambiguity in outputs
- make safety and uncertainty explicit
- make citations machine-checkable

### 3. Generation layer

Location: `src/generate_answers.py`

Responsibilities:

- load the evaluation dataset
- construct prompts from `question` and `provided_context`
- call an LLM provider through an adapter interface
- write a run artifact set with metadata and benchmark-status fields
- maintain a separate reusable cache store for raw generations

Primary public outputs:

- `results/raw_generations.jsonl`
- `results/run_manifest.json`

Reusable cache store: `results/cache/raw_generations_cache.jsonl`

### 4. Evaluation layer

Locations:

- `src/metrics.py`
- `src/run_evaluation.py`

This layer computes metric scores and applies safety flags.

Metric families in v1:

- Format compliance: checks that required sections are present and non-empty
- Citation validity: checks that cited anchors actually exist in the case context
- Required citation coverage: confirms required anchors appear in rationale bullets for certain cases
- Uncertainty alignment: checks that refuse/uncertain cases use explicit limitation language and that answer cases do not slip into insufficiency-style refusal wording
- Gold key point coverage: supporting checklist-style coverage against dataset-provided `gold_key_points`
- Faithfulness proxy: conservative heuristic using citation presence, lexical overlap, and a narrow sparse-context warning path for unsupported disease-specific elaboration

Current issue tags:

- Hard-failure tags: `UNSAFE_RECOMMENDATION`, `UNSUPPORTED_CITATION`, `REFUSAL_FAILURE`
- Warning tags: `HALLUCINATED_FACT`, `UNSUPPORTED_SPECIFICITY`, `UNCERTAINTY_MISALIGNED`, `LOW_FAITHFULNESS`, `MISSING_REQUIRED_CITATIONS`, `FORMAT_NONCOMPLIANT`

Primary output: `results/evaluation_output.csv`

Flagged subset: `results/flagged_cases.jsonl`

### 5. Reporting layer

Location: `src/summarize_results.py`

Creates a human-readable report for quick review.

Primary output: `results/summary.md`

Includes:

- PASS / WARN / FAIL distribution
- mean metric scores
- failure tag counts
- worst performing cases

### 6. Derived reviewer package layer

Location: `src/build_reviewer_report.py`

Creates a non-canonical reviewer package from a completed run. This layer is a
read-only convenience view over existing artifacts; it does not rescore cases,
change artifact meaning, or replace canonical outputs.

Primary outputs:

- `reviewer_packages/<provider>_<model_id>_<run_id>/reviewer_report.html`
- `reviewer_packages/<provider>_<model_id>_<run_id>/reviewer_summary.json`

Source artifacts:

- `results/run_manifest.json`
- `results/evaluation_output.csv`
- `results/flagged_cases.jsonl`
- `results/summary.md`
- `results/raw_generations.jsonl`

Design intent:

- make human review faster
- preserve source artifact provenance and links
- keep derived reviewer views outside canonical `results/`

## Benchmark-Defining vs Explanatory Files

These files define benchmark meaning and should not be edited casually:

- `dataset/clinical_questions.csv`
- `src/prompt_templates.py`
- `src/generate_answers.py`
- `src/metrics.py`
- `src/run_evaluation.py`
- `results/`

Generated reviewer packages under `reviewer_packages/` are derived convenience
outputs, not benchmark-defining artifacts.

This document, by contrast, is explanatory. It should help reviewers understand the system without changing evaluation semantics.

## Evaluation Philosophy

This sandbox is designed around healthcare risk thinking, not accuracy alone.

Key principles:

- prefer safe refusals over confident invention
- require evidence-backed reasoning through citations
- treat unsafe recommendations as hard failures
- surface failure patterns for human review

## Deployment Model

The pipeline is intended to run via GitHub Actions.

High-level workflow:

- offline verification for checked-in published artifacts
- sandbox runs for exploratory or mock-backed evaluation
- published benchmark candidate generation with full-dataset guardrails and reproducibility checks
- derived reviewer package generation for local or uploaded human inspection

The checked-in `results/` directory represents the canonical published benchmark set. Published candidates are intended for manual review before repo-tracked artifacts are updated.

The repo also includes a separate offline verification workflow that regenerates the checked-in published run from the cache store and checks the artifacts for exact reproducibility.

## Limitations

This sandbox is not clinical validation.

Known limitations:

- faithfulness is a heuristic proxy, not full entailment verification
- safety detection is pattern-based and incomplete by design
- no clinician adjudication is included in v1
- context snippets are simplified and not exhaustive

This project should be interpreted as an evaluation prototype and portfolio artifact, not a regulated system.

## Suggested Reading Order

- Start with `README.md` for project scope and artifact map.
- Read `docs/artifacts_guide.md` for artifact meanings and file-by-file review guidance.
- Read `docs/safety_case.md` for safety framing and non-claims.
- Read `docs/failure_modes.md` for failure taxonomy and the documented v1 limitation.
- Read `docs/notable_failures.md` for representative examples.
- Read `docs/reviewer_package.md` for derived package usage and boundaries.
- Read `docs/maintenance_boundaries.md` for protected benchmark areas.
