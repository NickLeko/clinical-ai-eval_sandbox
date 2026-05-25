# Clinical AI Evaluation Sandbox

A lightweight, safety-oriented evaluation harness for testing how LLMs behave in controlled clinical decision-support scenarios.

This repository is an evaluation artifact. It is not a medical device, not a clinical product, and not for patient care.

## Scope Boundary

This is a synthetic, demo-only evaluation sandbox.

- No PHI handling is implemented or claimed.
- No real patient data is included or expected.
- No EHR, clinical workflow, ordering, prescribing, alerting, or diagnostic integration is implemented.
- No output should be used as medical advice or patient-specific clinical decision support.
- The quick reviewer path below uses the deterministic `mock` provider and does not require an API key.

## Published Run Snapshot

Checked-in canonical published run, from `results/run_manifest.json` and `results/summary.md`:

| Field | Current checked-in value |
|---|---:|
| Provider / model | `openai` / `gpt-4o` |
| Run ID | `20260305_045410` |
| Scored cases | `25 / 25` |
| PASS / WARN / FAIL | `22 / 3 / 0` |
| Unsafe recommendation rate | `0.0%` |
| Hallucination suspicion rate | `0.0%` |
| Refusal failure rate | `0.0%` |
| Mean faithfulness proxy | `0.866` |
| Mean uncertainty alignment | `0.932` |

Guardrail: these are heuristic evaluator outputs for one explicit published run. They are not evidence of clinical safety or deployment readiness.
The checked-in published artifacts reflect the current stricter evaluator rules, including non-empty section checks and rationale-scoped required citations.

Historical raw generations used for cache/reproducibility are stored separately under `results/cache/` and are not the published benchmark result set.

## Quick Reviewer Path

Use this path to go from a fresh clone to a small local evaluation without touching the checked-in published artifacts.

### 1. Install And Verify

From the repo root:

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

`make verify` runs:

```bash
python -m unittest discover -s tests -v
python -m py_compile src/*.py tests/*.py
```

### 2. Run A Small Deterministic Eval

This uses the `mock` provider, writes outside canonical `results/`, and is suitable for reviewer smoke testing.

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

### 3. Inspect The Smoke Run

Open these local artifacts:

- `sandbox_results/reviewer_smoke/run_manifest.json`: run identity, dataset hash, case order, cache/live generation counts.
- `sandbox_results/reviewer_smoke/evaluation_output.csv`: case-level scores, flags, failure tags, and PASS/WARN/FAIL grades.
- `sandbox_results/reviewer_smoke/flagged_cases.jsonl`: WARN/FAIL subset for manual review.
- `sandbox_results/reviewer_smoke/summary.md`: top-line report for the smoke run.

The `sandbox_results/` directory is ignored by git and is not a published benchmark result.

### 4. Inspect The Checked-In Published Run

For the current canonical published run, start here:

1. [`results/run_manifest.json`](results/run_manifest.json): provider, model, run ID, prompt version, dataset hash, case count, and generation provenance.
2. [`results/summary.md`](results/summary.md): scorecard, safety-style rates, failure tags, and worst cases.
3. [`results/flagged_cases.jsonl`](results/flagged_cases.jsonl): three current WARN cases for qualitative review.
4. [`docs/REVIEWER_WORKFLOW.md`](docs/REVIEWER_WORKFLOW.md): artifact trust boundaries and review order.
5. [`docs/artifacts_guide.md`](docs/artifacts_guide.md): file-by-file artifact interpretation.

## What This Project Is

This project simulates a pre-deployment healthcare AI evaluation workflow:

- run a fixed clinical evaluation dataset
- generate structured model responses from a fixed prompt template
- score outputs with safety- and faithfulness-oriented heuristics
- surface flagged cases for human review
- summarize benchmark artifacts for reviewer inspection

The goal is not to build a medical model. The goal is to build a credible evaluation sandbox that shows how a healthcare AI team might risk-test an LLM before workflow integration.

## What It Evaluates

The benchmark uses structured clinical scenarios and checks whether a model:

- answers from the provided context instead of inventing facts
- cites the allowed context anchors
- expresses uncertainty or refuses when evidence is insufficient
- avoids forbidden or unsafe actions
- follows a response format that is easy to inspect and score

## What It Does Not Claim

This repository does not claim:

- clinical validity
- clinician-grade adjudication
- regulatory readiness
- complete safety coverage
- real-world deployment approval

Faithfulness and safety checks are heuristic by design. Results should be interpreted as a controlled evaluation artifact, not as proof that a model is clinically safe.

## Why It Matters

Clinical AI evaluation cannot rely on accuracy alone. This sandbox focuses on signals that matter in healthcare settings:

- faithfulness to provided context
- citation validity
- uncertainty and refusal behavior
- unsafe recommendation detection
- reviewer-friendly failure analysis

The repo is intentionally small, auditable, and governance-oriented rather than production-complete.

## 2-Minute Repo Map

```text
clinical-AI-eval_sandbox/
├── dataset/
│   └── clinical_questions.csv      # Fixed evaluation cases
├── src/
│   ├── prompt_templates.py         # Prompt template used for all cases
│   ├── llm_clients.py              # Provider adapters
│   ├── generate_answers.py         # Runs model generation and caches outputs
│   ├── metrics.py                  # Scoring and safety flags
│   ├── run_evaluation.py           # Applies metrics to generations
│   ├── summarize_results.py        # Builds markdown summary
│   └── build_reviewer_report.py    # Builds derived local reviewer package
├── results/
│   ├── raw_generations.jsonl       # One explicit published provider/model/run
│   ├── run_manifest.json           # Published run identity and provenance
│   ├── evaluation_output.csv       # Scored case-level results
│   ├── flagged_cases.jsonl         # WARN/FAIL subset for review
│   ├── summary.md                  # Human-readable run summary
│   └── cache/
│       └── raw_generations_cache.jsonl   # Reusable raw-generation cache/history store
├── docs/
│   ├── architecture.md             # System overview
│   ├── artifacts_guide.md          # File-by-file artifact guide
│   ├── REVIEWER_WORKFLOW.md        # Artifact trust map and review order
│   ├── reviewer_package.md         # Derived reviewer package boundaries and usage
│   ├── reviewer_guide.md           # Fast reviewer walkthrough
│   ├── results_interpretation.md   # Benchmark interpretation guidance
│   ├── safety_case.md              # Safety framing and hazards
│   ├── failure_modes.md            # Failure taxonomy and known limitations
│   ├── notable_failures.md         # Representative cases
│   ├── CODEX_RUNBOOK.md            # Repo-local Codex workflow
│   └── maintenance_boundaries.md   # Eval-sensitive change policy
├── AGENTS.md                       # Codex operating constraints
├── Makefile                        # Local verification helpers
├── requirements.txt
└── README.md
```

## Evaluation Pipeline

```text
dataset/clinical_questions.csv
-> src/prompt_templates.py
-> src/generate_answers.py
-> results/raw_generations.jsonl + results/run_manifest.json
-> src/run_evaluation.py + src/metrics.py
-> results/evaluation_output.csv + results/flagged_cases.jsonl
-> src/summarize_results.py
-> results/summary.md
```

## Core Outputs

The main review artifacts are:

- `results/raw_generations.jsonl`: raw prompts, answers, and metadata for the one published run
- `results/run_manifest.json`: the explicit provider / model / run_id backing the public artifacts
- `results/evaluation_output.csv`: case-level metrics, flags, and PASS/WARN/FAIL grades
- `results/flagged_cases.jsonl`: subset for manual inspection of concerning outputs
- `results/summary.md`: compact benchmark report with rates, means, and worst cases
- `results/cache/raw_generations_cache.jsonl`: reusable raw-generation cache/history store that is not itself the public benchmark set

The reviewer package is a generated convenience view, not a canonical benchmark artifact. It is derived from completed-run artifacts without changing scoring, prompts, datasets, thresholds, tags, metrics definitions, or published artifact meaning.

To generate it locally:

```bash
make reviewer-package
```

Equivalent direct command:

```bash
python src/build_reviewer_report.py --results-dir results
```

Then open `reviewer_packages/<provider>_<model_id>_<run_id>/reviewer_report.html` in a browser. The package is ignored by git and also includes `reviewer_summary.json`, a machine-readable derived summary that mirrors the HTML sections. The generator validates run identity and flagged-case overlap before rendering.

## Evidence Trail For Reviewers

Claims about safety, governance, determinism, and auditability in this repo are tied to concrete files:

| Reviewer question | Concrete repo evidence |
|---|---|
| What exact run produced the checked-in results? | `results/run_manifest.json` records `provider`, `model_id`, `run_id`, `prompt_version`, `run_kind`, and `benchmark_status`. |
| Was the same fixed dataset used? | `results/run_manifest.json` records `dataset_sha256`, `case_count`, and ordered `case_ids`; `tests/test_dataset_integrity.py` checks dataset structure. |
| Are generated outputs auditable? | `results/raw_generations.jsonl` stores each prompt, answer, run metadata, generation mode, cache key, and raw provider response payload. |
| Are scored outputs tied back to run identity? | `src/run_evaluation.py` validates raw-generation run identity and dataset hash before scoring; `tests/test_artifact_consistency.py` checks manifest/evaluation/flagged-case alignment. |
| What do PASS/WARN/FAIL mean? | `src/metrics.py` defines the tags and grade policy; `docs/results_interpretation.md` explains how to read them without clinical overclaiming. |
| How are safety and refusal signals represented? | `dataset/clinical_questions.csv` includes `expected_behavior` and `forbidden_actions`; `src/metrics.py` emits tags such as `UNSAFE_RECOMMENDATION`, `REFUSAL_FAILURE`, and `UNCERTAINTY_MISALIGNED`; `tests/test_metrics.py` locks representative behavior. |
| Can a reviewer run it without API access? | The `mock` provider in `src/llm_clients.py` supports deterministic local smoke runs; the quick reviewer path writes to ignored `sandbox_results/`. |
| What prevents derived views from becoming source-of-truth results? | `docs/REVIEWER_WORKFLOW.md`, `docs/reviewer_package.md`, `.gitignore`, and reviewer-package validation keep generated views outside canonical `results/`. |

## Running The Project

This repo separates offline verification, exploratory sandbox runs, and published benchmark candidates.

### Offline verification

The `Offline Verification` workflow compiles the repo, runs the unit tests, regenerates the published run from `results/cache/raw_generations_cache.jsonl`, and checks that the public artifacts reproduce exactly.

### Quick local verification

For a fast local health check before reviewing deeper:

```bash
python -m unittest discover -s tests -v
python -m py_compile src/*.py tests/*.py
```

The same checks are available through:

```bash
make verify
```

### Working with Codex

Repo-local Codex guidance lives in `AGENTS.md`, with the operational runbook in `docs/CODEX_RUNBOOK.md`.

Future Codex sessions should classify changes as docs-only maintenance, derived tooling, sandbox support, benchmark revision, or result refresh before editing. Benchmark-defining files and checked-in `results/` artifacts should only change when that is the explicit task.

### Sandbox runs

The `Clinical AI Eval (Sandbox Run)` workflow is the API-backed path for exploratory runs.

Use it for:

- partial-dataset smoke tests
- prompt iteration checks
- provider comparisons
- `mock`-provider validation runs

Sandbox runs write to `sandbox_results/` inside the workflow and upload artifacts for review. They do not overwrite `results/`.

### Published benchmark candidate

The `Clinical AI Eval (Published Benchmark Candidate)` workflow is the guarded path for generating a full-dataset benchmark candidate for manual review.

It:

- forces the full dataset
- rejects the `mock` provider
- runs compile + unit-test checks first
- generates a live run, then rebuilds the candidate artifact set from cache
- verifies exact reproducibility before uploading the candidate artifacts

Published candidates are uploaded for manual review rather than pushed directly back to the repo.

Expected workflow inputs:

| Input | Example | Description |
|---|---|---|
| `model` | `gpt-4o` | Model used for generation |
| `prompt_version` | `v1` | Prompt label tracked in artifacts |
| `run_id` | `20260330_candidate` | Explicit benchmark-candidate run identifier |

### Local script entry points

If a reviewer wants to inspect the mechanics, the main scripts are:

- `src/generate_answers.py`
- `src/run_evaluation.py`
- `src/summarize_results.py`
- `src/build_reviewer_report.py`

`src/generate_answers.py` supports `--run-kind sandbox`, `--run-kind candidate`, and `--run-kind published`.
Use `sandbox` for exploratory or partial runs, `candidate` for full-dataset review artifacts, and `published` only for the checked-in canonical benchmark set and offline reproducibility.

Supported generation providers for `src/generate_answers.py`:

- `openai` using `OPENAI_API_KEY`
- `anthropic` using `ANTHROPIC_API_KEY`
- `gemini` using `GEMINI_API_KEY` or `GOOGLE_API_KEY`
- `mock` for deterministic pipeline validation without API access

The multi-provider support above exists at the generation-script layer. The checked-in GitHub Actions workflows currently wire `openai` for API-backed runs and `mock` for pipeline validation; using `anthropic` or `gemini` in CI would require extending workflow secrets and inputs.

## Documentation Guide

- `docs/architecture.md`: architecture, modules, and data flow
- `docs/artifacts_guide.md`: what each results artifact contains and how to read it
- `docs/REVIEWER_WORKFLOW.md`: step-by-step artifact review order and source-of-truth guidance
- `docs/reviewer_package.md`: derived reviewer package usage, source dependencies, and boundaries
- `docs/results_interpretation.md`: how to interpret benchmark outputs and model comparisons responsibly
- `docs/safety_case.md`: safety framing, hazards, and mitigations
- `docs/failure_modes.md`: common failure categories plus known v1 limitations
- `docs/notable_failures.md`: representative flagged cases
- `docs/reviewer_guide.md`: quick walkthrough for interviewers and other reviewers
- `docs/CODEX_RUNBOOK.md`: repo-local operating workflow for future Codex sessions
- `docs/maintenance_boundaries.md`: what should not be edited casually because it can change benchmark meaning

## Eval-Sensitive Areas

The following files are benchmark-sensitive and should be treated as protected unless a benchmark revision is explicitly intended:

- `dataset/clinical_questions.csv`
- `src/prompt_templates.py`
- `src/metrics.py`
- `src/run_evaluation.py`
- `src/generate_answers.py`
- `results/run_manifest.json`
- `results/summary.md`
- `results/evaluation_output.csv`
- `results/flagged_cases.jsonl`
- `results/raw_generations.jsonl`

See `docs/maintenance_boundaries.md` for the maintenance policy used in this repo.

## Known Scope Boundaries

- The dataset is intentionally small and reviewable.
- Safety flags are heuristic and incomplete.
- Reported results are one explicit published provider / model / run, not universal model judgments.
- Human clinical review is outside the automated pipeline.
- Historical cached raw generations are kept separate from the published benchmark result set.

## Governance Signals

It demonstrates:

- healthcare AI evaluation framing
- safety-aware benchmark design
- structured prompt and scoring discipline
- honest limitations and governance thinking
- reviewer-friendly artifact organization

## Disclaimer

This repository demonstrates evaluation methods for healthcare AI systems. It must not be used to provide medical advice, support patient care, or make clinical decisions.
