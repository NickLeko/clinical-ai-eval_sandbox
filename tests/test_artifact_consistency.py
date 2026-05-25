import csv
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"
RUN_MANIFEST_PATH = RESULTS_DIR / "run_manifest.json"
EVALUATION_OUTPUT_PATH = RESULTS_DIR / "evaluation_output.csv"
FLAGGED_CASES_PATH = RESULTS_DIR / "flagged_cases.jsonl"
SUMMARY_PATH = RESULTS_DIR / "summary.md"
RAW_GENERATIONS_PATH = RESULTS_DIR / "raw_generations.jsonl"


def load_manifest() -> dict:
    with RUN_MANIFEST_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_evaluation_rows() -> list[dict[str, str]]:
    with EVALUATION_OUTPUT_PATH.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_flagged_rows() -> list[dict]:
    rows = []
    with FLAGGED_CASES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


class PublishedArtifactConsistencyTests(unittest.TestCase):
    def test_published_artifact_files_exist_and_are_readable(self) -> None:
        for path in (
            RUN_MANIFEST_PATH,
            EVALUATION_OUTPUT_PATH,
            FLAGGED_CASES_PATH,
            SUMMARY_PATH,
            RAW_GENERATIONS_PATH,
        ):
            self.assertTrue(path.exists(), f"Missing artifact: {path}")
            path.read_text(encoding="utf-8")

        self.assertTrue(load_manifest())
        self.assertTrue(load_evaluation_rows())
        load_flagged_rows()

    def test_manifest_preserves_auditable_published_run_metadata(self) -> None:
        manifest = load_manifest()

        for field in [
            "run_id",
            "provider",
            "model_id",
            "prompt_version",
            "run_kind",
            "benchmark_status",
            "dataset_path",
            "dataset_sha256",
            "dataset_total_rows",
            "is_full_dataset_run",
            "case_count",
            "case_ids",
            "cache_hits",
            "live_generations",
            "generation_modes",
            "source_run_ids",
        ]:
            self.assertIn(field, manifest)

        self.assertEqual(manifest["run_kind"], "published")
        self.assertEqual(manifest["benchmark_status"], "canonical_published")
        self.assertTrue(manifest["is_full_dataset_run"])
        self.assertEqual(int(manifest["case_count"]), int(manifest["dataset_total_rows"]))
        self.assertEqual(len(manifest["case_ids"]), int(manifest["case_count"]))
        self.assertRegex(manifest["dataset_sha256"], re.compile(r"^[0-9a-f]{64}$"))
        self.assertEqual(
            int(manifest["cache_hits"]) + int(manifest["live_generations"]),
            int(manifest["case_count"]),
        )
        self.assertEqual(
            sum(int(count) for count in manifest["generation_modes"].values()),
            int(manifest["case_count"]),
        )

    def test_evaluation_output_exposes_reviewer_metric_and_flag_columns(self) -> None:
        rows = load_evaluation_rows()
        columns = set(rows[0])

        expected_columns = {
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
            "bogus_citations",
            "hallucination_suspected",
            "unsupported_specificity_suspected",
            "unsafe_recommendation",
            "refusal_failure",
            "format_compliance",
            "citation_validity",
            "required_citations",
            "uncertainty_alignment",
            "gold_key_points_coverage",
            "faithfulness_proxy",
        }

        self.assertTrue(expected_columns.issubset(columns))

    def test_summary_preserves_interpretation_and_scope_guardrails(self) -> None:
        summary = SUMMARY_PATH.read_text(encoding="utf-8")

        self.assertIn("Status: **Canonical published benchmark run**", summary)
        self.assertIn("not evidence of clinical safety or deployment readiness", summary)
        self.assertIn("Historical cached generations are stored separately under `results/cache/`", summary)
        self.assertIn("Unsafe recommendation rate", summary)
        self.assertIn("Refusal failure rate", summary)

    def test_run_identity_matches_between_manifest_and_evaluation_output(self) -> None:
        manifest = load_manifest()
        rows = load_evaluation_rows()

        for row in rows:
            self.assertEqual(row["run_id"], manifest["run_id"], row["case_id"])
            self.assertEqual(row["provider"], manifest["provider"], row["case_id"])
            self.assertEqual(row["model_id"], manifest["model_id"], row["case_id"])
            self.assertEqual(row["prompt_version"], manifest["prompt_version"], row["case_id"])

    def test_case_ids_match_manifest_and_flagged_subset(self) -> None:
        manifest = load_manifest()
        evaluation_rows = load_evaluation_rows()
        flagged_rows = load_flagged_rows()

        manifest_case_ids = [str(case_id) for case_id in manifest["case_ids"]]
        evaluation_case_ids = [row["case_id"] for row in evaluation_rows]
        flagged_case_ids = [row["case_id"] for row in flagged_rows]

        self.assertEqual(evaluation_case_ids, manifest_case_ids)
        self.assertEqual(len(evaluation_case_ids), int(manifest["case_count"]))
        self.assertEqual(len(evaluation_case_ids), len(set(evaluation_case_ids)))
        self.assertTrue(set(flagged_case_ids).issubset(set(evaluation_case_ids)))

    def test_flagged_rows_match_evaluation_rows_where_fields_overlap(self) -> None:
        manifest = load_manifest()
        evaluation_by_case = {row["case_id"]: row for row in load_evaluation_rows()}

        # flagged_cases.jsonl does not carry run_id/provider; model and prompt are the overlapping run identity fields.
        for flagged in load_flagged_rows():
            case_id = flagged["case_id"]
            evaluation = evaluation_by_case[case_id]

            self.assertEqual(flagged["model_id"], manifest["model_id"], case_id)
            self.assertEqual(flagged["prompt_version"], manifest["prompt_version"], case_id)
            self.assertEqual(flagged["overall_grade"], evaluation["overall_grade"], case_id)
            self.assertEqual(flagged["failure_tags"], evaluation["failure_tags"], case_id)
            self.assertIn(flagged["overall_grade"], {"WARN", "FAIL"}, case_id)


if __name__ == "__main__":
    unittest.main()
