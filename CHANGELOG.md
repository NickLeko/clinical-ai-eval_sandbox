# Changelog

## 0.3.0 — 2026-10-14 (untagged)

Explicit benchmark revision and offline result refresh from audit commit `1429ca01`:
closed the unrelated-predicate negation fallback; expanded literal acceptance pairs;
added zero whole-answer/Recommendation coverage warnings and a context-copy canary;
moved Gemini credentials to headers and removed credential-bearing error details;
made oversized answers FAIL individually with other scoring skipped and kept citation deduplication in sets; patched and hashed
dependencies with a failing CI audit step. No prompts, dataset cases, or provider
answers changed. No live model generation or release tag.

The v0.2.0 21/3/1 distribution is historical, superseded by 13/11/1 under the new
rules; this is not a model-performance improvement or regression. See the
[v0.3.0 release notes](docs/releases/0.3.0.md) for every case and responder.

## 0.2.0 — 2026-09-05

Explicit benchmark revision and offline result refresh: blocking adversarial minimal
pairs and mock canary; narrow clause-negation gates; four missing literal case gates;
uncancelable recognized refusal violations; `ANSWER_WITHHELD` warnings; provider
completion status; cache/prompt/dataset integrity; scored-artifact receipts and stale
view rejection; safe workflow-input handling; retired safety headline and corrected
claims. No new NLP dependencies or live model generation.

See [release notes](docs/releases/0.2.0.md) for counts, migration, and open audit findings.
The previously untagged prototype is treated as the 0.1 baseline.
