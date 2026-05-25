# Reviewer Guide

## Who This Is For

This guide is for a technical healthcare AI reviewer who wants to understand, run, and audit the repository without reading every source file first.

The project is a synthetic evaluation sandbox. It is not a medical device, not a clinical product, not a PHI system, and not a source of medical advice.

## Quick Reviewer Path

### 1. Install And Verify

From the repo root after cloning:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Dependency installation requires package-index access unless the packages are already available from a local cache.

Then run:

```bash
make verify
```

`make verify` runs unit tests and Python compilation. It should pass before trusting local changes.

### 2. Run A Small Local Eval

Use the deterministic `mock` provider for a no-API smoke run:

```bash
python src/generate_answers.py \
  --dataset dataset/clinical_questions.csv \
  --provider mock \
  --model mock-clinical-model \
  --prompt-version reviewer-smoke \
  --run-id reviewer_smoke \
  --max-cases 3 \
  --results-dir sandbox_results/reviewer_smoke \
  --run-kind sandbox

python src/run_evaluation.py \
  --dataset dataset/clinical_questions.csv \
  --results-dir sandbox_results/reviewer_smoke

python src/summarize_results.py \
  --top-n 5 \
  --results-dir sandbox_results/reviewer_smoke
```

This writes to `sandbox_results/reviewer_smoke/`, which is ignored by git and non-canonical.

### 3. Inspect The Smoke Run

- `sandbox_results/reviewer_smoke/run_manifest.json`: provider, model, run ID, dataset hash, case order, cache hits, and live generation count.
- `sandbox_results/reviewer_smoke/evaluation_output.csv`: case-level metric values, boolean flags, failure tags, and PASS/WARN/FAIL grades.
- `sandbox_results/reviewer_smoke/flagged_cases.jsonl`: WARN/FAIL subset for manual review.
- `sandbox_results/reviewer_smoke/summary.md`: compact scorecard and interpretation guardrails.

### 4. Inspect The Published Run

Use the checked-in artifacts for the repo's current published benchmark snapshot:

1. `results/run_manifest.json`: confirm `benchmark_status: canonical_published`, provider/model/run ID, prompt version, dataset hash, and 25/25 case coverage.
2. `results/summary.md`: read the scorecard and heuristic safety rates.
3. `results/flagged_cases.jsonl`: inspect the current WARN cases and answer text.
4. `results/evaluation_output.csv`: cross-check all case-level scores and flags.
5. `results/raw_generations.jsonl`: audit exact prompts, answers, generation metadata, and raw provider payloads.

### 5. Optional Browser-Friendly Package

Run:

```bash
make reviewer-package
```

Then open `reviewer_packages/<provider>_<model_id>_<run_id>/reviewer_report.html`.

Treat `reviewer_report.html` and `reviewer_summary.json` as derived convenience outputs only. They do not rescore cases, change artifact meanings, or replace canonical files under `results/`.

## What This Repo Demonstrates

The repository is strongest as a signal of:

- healthcare AI evaluation judgment
- safety-first benchmarking
- faithfulness and uncertainty awareness
- structured artifact design
- honest limitations and governance thinking

## Evidence To Check

- Scope boundary: `README.md`, `docs/safety_case.md`, and this guide explicitly state no clinical use, no PHI workflow, no patient care, and no deployment claim.
- Fixed inputs: `dataset/clinical_questions.csv` is the stable synthetic case set; `results/run_manifest.json` records `dataset_sha256` and ordered `case_ids`.
- Prompt contract: `src/prompt_templates.py` defines the structured response sections required for automated review.
- Scoring semantics: `src/metrics.py` defines metric scores, issue tags, and PASS/WARN/FAIL policy; `docs/results_interpretation.md` explains how to interpret them.
- Refusal and safety behavior: `expected_behavior` and `forbidden_actions` live in the dataset; representative scoring behavior is covered in `tests/test_metrics.py`.
- Auditability: `results/raw_generations.jsonl` stores prompt/answer metadata, while `results/evaluation_output.csv` and `results/flagged_cases.jsonl` expose scored evidence.
- Determinism checks: `make verify`, `tests/test_artifact_consistency.py`, and the `Offline Verification` workflow check artifact alignment and reproducibility.

## What To Read If You Want More Depth

- `docs/REVIEWER_WORKFLOW.md` for artifact trust boundaries and review order
- `docs/artifacts_guide.md` for file-by-file artifact meanings
- `docs/architecture.md` for the dataset -> prompt -> generation -> scoring -> reporting flow
- `docs/safety_case.md` for hazard framing and mitigation logic
- `docs/failure_modes.md` for the failure taxonomy and known evaluator limits
- `docs/notable_failures.md` for representative WARN cases in the published run

## What This Repo Does Not Claim

This project does not claim:

- clinical validation
- production readiness
- regulatory approval
- clinician adjudication
- complete safety coverage
- PHI readiness
- medical advice or diagnostic support

It is an evaluation sandbox and portfolio artifact, not a medical product.

## Benchmark Boundary Reminder

If you are reviewing maintenance quality, the benchmark-defining files are intentionally treated as protected. Documentation can be improved freely, but changes to dataset content, prompt behavior, scoring logic, safety flags, or reported artifacts should be treated as explicit evaluation revisions.

## Suggested Reviewer Takeaway

The main takeaway is not that any specific model is safe for healthcare use. The main takeaway is that even capable models can still trigger safety-relevant warnings or failures, and that a disciplined evaluation harness is necessary before deployment.
