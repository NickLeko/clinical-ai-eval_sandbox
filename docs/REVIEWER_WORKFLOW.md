# Reviewer Workflow

> v0.2.0 integrity boundary: `evaluation_manifest.json` is required. It binds the
> scored raw text, run manifest, evaluation CSV, complete flagged subset, evaluator
> code, and executed blocking acceptance result; summary adds its own hash.
> Summary/reviewer commands reject stale or unscored files and require the readable
> dataset named in the manifest. Re-run evaluation and then summary after changes.
> Legacy artifacts require an explicit re-score; the historical audit bundle is
> preserved under `audits/adversarial_2026_09_04/baseline/`.
> This is a consistency receipt, not a signed attestation or clinical safety evidence.


Use this workflow to inspect one run without confusing canonical artifacts, derived views, and cache/history files.

## Artifact Trust Map

| Artifact | Use it for | Authoritative for | Not authoritative for |
|---|---|---|---|
| `results/run_manifest.json` | Confirm run identity and provenance before reading scores. | Provider, model, run ID, prompt version, run kind, benchmark status, dataset coverage, case order, cache/live generation provenance. | Case-level scoring, clinical meaning, or model safety. |
| `results/evaluation_output.csv` | Inspect the full scored case table. | Case-level metric values, boolean safety flags, failure tags, PASS/WARN/FAIL grades, run metadata per row. | Raw prompts/answers, clinician adjudication, or proof of clinical safety. |
| `results/flagged_cases.jsonl` | Review WARN/FAIL examples quickly. | The flagged subset plus question, provided context, gold key points, answer text, grade, and failure tags for those cases. | The full benchmark population, absence of risk in non-flagged cases, or aggregate rates. |
| `results/summary.md` | Get the fastest top-level snapshot. | Headline distribution, rates, means, failure tag counts, and worst-case table for the artifact set. | Detailed case evidence or replacement for `evaluation_output.csv` and flagged-case review. |
| `reviewer_packages/<provider>_<model_id>_<run_id>/reviewer_report.html` | Use a browser-friendly local view of the manifest, distributions, tags, flags, review-first cases, and flagged details. | Nothing canonical; it is a derived convenience view generated from completed-run artifacts. | Scoring logic, artifact meaning, or source-of-truth results. |
| `reviewer_packages/<provider>_<model_id>_<run_id>/reviewer_summary.json` | Use a machine-readable mirror of the HTML reviewer-package sections for future tooling. | Nothing canonical; it is derived from the same completed-run artifacts as the HTML. | Scoring logic, artifact meaning, or source-of-truth results. |
| `results/raw_generations.jsonl` | Audit the exact model inputs and outputs when needed. | Raw prompt text, answer text, provider response payload, and generation metadata for the published run. | Scored grades or aggregate benchmark interpretation. |

## Recommended Review Order

1. Start with `results/run_manifest.json`.
   Confirm `provider`, `model_id`, `run_id`, `prompt_version`, `benchmark_status`, and dataset coverage before trusting any other artifact.
2. Read `results/summary.md` if present.
   Use it for orientation only.
3. Generate the derived reviewer package if a browser view or structured convenience summary is useful.
   Treat it as a local reader for the same artifacts, not a new result.
4. Open `results/flagged_cases.jsonl`.
   Inspect WARN/FAIL cases qualitatively, especially failure tags and answer text.
5. Use `results/evaluation_output.csv`.
   Cross-check full-population scores, flags, and grade distribution.
6. Inspect `results/raw_generations.jsonl` only when you need full prompt/answer audit detail.

## Generate The Reviewer Package

The package is self-contained, local, and ignored by git. It writes outside canonical `results/` by default.

```bash
make reviewer-package
```

Equivalent direct command:

```bash
python src/build_reviewer_report.py --results-dir results
```

Default output:

```text
reviewer_packages/<provider>_<model_id>_<run_id>/
├── reviewer_report.html
└── reviewer_summary.json
```

Open `reviewer_report.html` in a browser. The package validates manifest/evaluation run identity, completed-run source artifact presence, and overlapping fields between `evaluation_output.csv` and `flagged_cases.jsonl` before rendering.

The older `make reviewer-report` target remains as an alias for `make reviewer-package`.

## Common Mistakes

- Do not treat PASS as proof that a model is clinically safe.
- Do not treat WARN/FAIL as clinician adjudication; they are heuristic review signals.
- Do not use `flagged_cases.jsonl` as the denominator for rates; use `evaluation_output.csv`.
- Do not treat the reviewer package as canonical. Regenerate it from artifacts when needed.
- Do not check generated reviewer packages into `results/`.
- Do not compare sandbox, candidate, and published runs without checking `run_manifest.json`.
- Do not treat `results/cache/raw_generations_cache.jsonl` as the published benchmark set.
