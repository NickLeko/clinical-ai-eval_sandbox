# Artifacts Guide

> v0.2.0 integrity boundary: `evaluation_manifest.json` is required. It binds the
> scored raw text, run manifest, evaluation CSV, complete flagged subset, evaluator
> code, and executed blocking acceptance result; summary adds its own hash.
> Summary/reviewer commands reject stale or unscored files and require the readable
> dataset named in the manifest. Re-run evaluation and then summary after changes.
> Legacy artifacts require an explicit re-score; the historical audit bundle is
> preserved under `audits/adversarial_2026_09_04/baseline/`.
> This is a consistency receipt, not a signed attestation or clinical safety evidence.


This document explains what each benchmark artifact contains, how a reviewer should read it, and what each file does and does not imply.

Read this file if you want a file-by-file guide to the canonical outputs under `results/` and the derived reviewer package under `reviewer_packages/`.

## Artifact Set

The main benchmark artifacts are:

- `results/raw_generations.jsonl`
- `results/run_manifest.json`
- `results/evaluation_output.csv`
- `results/flagged_cases.jsonl`
- `results/summary.md`
- `results/cache/raw_generations_cache.jsonl`

These files serve different review purposes. They should be read together rather than as substitutes for one another.

The checked-in `results/` directory is the canonical published artifact set for this repo version. Sandbox and benchmark-candidate runs may use the same file shapes outside the checked-in repo, but those runs should be interpreted from their `run_kind`, `benchmark_status`, and dataset-coverage fields rather than assumed to be canonical.

Generated reviewer packages live outside the canonical artifact set under `reviewer_packages/` by default. They are derived convenience views and should be regenerated from source artifacts when needed.

## `results/raw_generations.jsonl`

What it contains:

- prompt text
- model answer text
- one explicit published run's metadata such as provider, model, prompt version, and run_id
- raw provider response payload for debugging

Why it matters:

- supports auditability
- shows the stored user prompt and returned answer
- helps reviewers inspect individual outputs in context

What it does not mean:

- it is not the scored benchmark by itself
- it does not tell you whether an output passed or failed without the evaluation layer
- it is not the raw generation history for every exploratory run in the repo

## `results/run_manifest.json`

What it contains:

- the explicit `provider`, `model_id`, and `run_id` for the artifact set
- `run_kind` and `benchmark_status` so reviewers can distinguish canonical published runs from sandbox or candidate artifacts
- dataset hash, dataset coverage, and case count
- provenance about whether the raw file was regenerated from cache or fresh model calls

Why it matters:

- makes the public benchmark set explicit and reproducible
- prevents accidental mixing of cached history with the published run

What it does not mean:

- it is not a scored artifact by itself
- it does not replace the raw, evaluated, and summarized outputs

## `results/evaluation_output.csv`

What it contains:

- case identifiers and run metadata
- metric scores
- boolean safety flags
- failure tags
- overall PASS / WARN / FAIL grading

Why it matters:

- this is the main structured scoring table
- it enables case-level comparison across runs, prompts, or models
- it makes the heuristic evaluation logic inspectable in tabular form

What it does not mean:

- it is not a clinician-adjudicated judgment set
- it should not be read as proof of real-world clinical safety

## `results/flagged_cases.jsonl`

What it contains:

- WARN and FAIL cases only
- the associated question, context, answer text, and failure tags

Why it matters:

- gives reviewers a faster path to concerning outputs
- supports manual inspection and qualitative failure review

What it does not mean:

- it is not the full benchmark population
- absence from this file does not prove a model is safe

## `results/summary.md`

What it contains:

- total cases scored
- PASS / WARN / FAIL distribution
- safety signal rates
- mean metric scores
- canonical vs non-canonical status plus dataset coverage
- failure tag counts
- a short worst-case table

Why it matters:

- provides the fastest top-level benchmark snapshot
- makes the repo easy to review in a few minutes

What it does not mean:

- it is a summary view, not the full evidence base
- it should be cross-checked with `evaluation_output.csv` and flagged examples when making interpretations

## `results/cache/raw_generations_cache.jsonl`

What it contains:

- reusable raw generations from prior runs
- response payloads used for cache hits and offline reproduction

Why it matters:

- keeps cache/history separate from the published benchmark set
- allows the public artifacts to be regenerated offline without re-calling the API when the exact run is already cached

What it does not mean:

- it is not the public benchmark result set
- rows in this file should not be treated as directly comparable published outputs unless they are selected into `results/raw_generations.jsonl`

## `reviewer_packages/.../reviewer_report.html` And `reviewer_summary.json`

What they contain:

- a self-contained HTML report for one completed run
- a machine-readable JSON summary that mirrors the HTML sections
- source artifact links, sizes, and SHA-256 hashes
- run metadata, grade distribution, score summaries, flag counts, tag counts, category and risk breakdowns
- review-first ordering for WARN/FAIL cases using only existing artifact fields
- per-flagged-case details assembled from `flagged_cases.jsonl` and validated evaluation rows

Why they matter:

- make human inspection faster
- give reviewers direct jump links from summaries to case details
- keep provenance visible while avoiding edits to canonical artifacts

What they do not mean:

- they are not canonical benchmark outputs
- they do not rescore or reinterpret cases
- they do not replace `evaluation_output.csv`, `flagged_cases.jsonl`, `summary.md`, or `raw_generations.jsonl`
- review-first ordering is not a new benchmark metric or severity definition

Generate them with:

```bash
make reviewer-package
```

## Suggested Review Order

1. Start with `results/run_manifest.json` to confirm the exact published provider / model / run.
2. Read `results/summary.md` for the high-level snapshot.
3. Generate the reviewer package if you want a faster HTML/JSON navigation layer.
4. Open `results/flagged_cases.jsonl` for representative concerning cases.
5. Use `results/evaluation_output.csv` for structured detail.
6. Inspect `results/raw_generations.jsonl` when you want full prompt-and-answer auditability for the published run.

## Interpretation Guardrails

- Treat these artifacts as benchmark-specific outputs, not universal model judgments.
- Treat heuristic flags as signals for review, not as definitive clinical conclusions.
- Treat `results/cache/raw_generations_cache.jsonl` as cache/history, not as the published benchmark set.
- Treat `reviewer_packages/` as derived convenience output, not as canonical results.
- Read the artifacts alongside `docs/results_interpretation.md` and `docs/maintenance_boundaries.md`.

## Related Docs

- `README.md` for the repo overview
- `docs/results_interpretation.md` for benchmark-reading guidance
- `docs/reviewer_guide.md` for a fast review path
- `docs/reviewer_package.md` for derived package usage and boundaries
- `docs/maintenance_boundaries.md` for protected artifact meaning
