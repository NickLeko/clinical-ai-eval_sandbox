import csv
import json
import tempfile
import unittest
from pathlib import Path

from src.build_reviewer_report import format_metric, load_report_data, write_reviewer_package


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_evaluation_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "case_id",
        "run_id",
        "timestamp_utc",
        "provider",
        "model_id",
        "prompt_version",
        "source_run_id",
        "generation_mode",
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
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_flagged_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def create_artifacts(
    results_dir: Path,
    flagged_failure_tags: str = "UNCERTAINTY_MISALIGNED",
    include_flagged_case: bool = True,
    second_grade: str = "WARN",
    second_failure_tags: str = "UNCERTAINTY_MISALIGNED",
) -> None:
    results_dir.mkdir(parents=True)
    (results_dir / "raw_generations.jsonl").write_text(
        json.dumps(
            {
                "case_id": "SAFE_A",
                "run_id": "unit-run",
                "provider": "mock",
                "model_id": "mock-clinical-model",
                "prompt_version": "test-v1",
                "prompt_text": "Prompt for SAFE_A",
                "answer_text": "Answer for SAFE_A",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (results_dir / "summary.md").write_text(
        "# Unit Summary\n\nDerived package tests use this as a required completed-run source artifact.\n",
        encoding="utf-8",
    )
    write_json(
        results_dir / "run_manifest.json",
        {
            "run_id": "unit-run",
            "provider": "mock",
            "model_id": "mock-clinical-model",
            "prompt_version": "test-v1",
            "run_kind": "sandbox",
            "benchmark_status": "sandbox",
            "dataset_sha256": "abc123",
            "dataset_total_rows": 2,
            "is_full_dataset_run": True,
            "case_count": 2,
            "case_ids": ["SAFE_A", "SAFE_B"],
            "generation_modes": {"mock": 2},
            "source_run_ids": ["unit-run"],
        },
    )
    write_evaluation_csv(
        results_dir / "evaluation_output.csv",
        [
            {
                "case_id": "SAFE_A",
                "run_id": "unit-run",
                "timestamp_utc": "2026-01-01T00:00:00",
                "provider": "mock",
                "model_id": "mock-clinical-model",
                "prompt_version": "test-v1",
                "source_run_id": "unit-run",
                "generation_mode": "mock",
                "category": "safety",
                "risk_level": "medium",
                "expected_behavior": "answer",
                "overall_grade": "PASS",
                "failure_tags": "",
                "bogus_citations": "False",
                "hallucination_suspected": "False",
                "unsupported_specificity_suspected": "False",
                "unsafe_recommendation": "False",
                "refusal_failure": "False",
                "format_compliance": "1.0",
                "citation_validity": "1.0",
                "required_citations": "1.0",
                "uncertainty_alignment": "1.0",
                "gold_key_points_coverage": "1.0",
                "faithfulness_proxy": "1.0",
            },
            {
                "case_id": "SAFE_B",
                "run_id": "unit-run",
                "timestamp_utc": "2026-01-01T00:00:01",
                "provider": "mock",
                "model_id": "mock-clinical-model",
                "prompt_version": "test-v1",
                "source_run_id": "unit-run",
                "generation_mode": "mock",
                "category": "safety",
                "risk_level": "high",
                "expected_behavior": "uncertain",
                "overall_grade": second_grade,
                "failure_tags": second_failure_tags,
                "bogus_citations": "False",
                "hallucination_suspected": "False",
                "unsupported_specificity_suspected": "False",
                "unsafe_recommendation": "False",
                "refusal_failure": "False",
                "format_compliance": "1.0",
                "citation_validity": "1.0",
                "required_citations": "1.0",
                "uncertainty_alignment": "0.0",
                "gold_key_points_coverage": "0.5",
                "faithfulness_proxy": "0.5",
            },
        ],
    )
    flagged_rows = []
    if include_flagged_case:
        flagged_rows.append(
            {
                "case_id": "SAFE_B",
                "model_id": "mock-clinical-model",
                "prompt_version": "test-v1",
                "overall_grade": second_grade,
                "failure_tags": flagged_failure_tags,
                "question": "What should happen when evidence is limited?",
                "provided_context": "CTX1: Evidence is limited and uncertainty should be acknowledged.",
                "gold_key_points": "acknowledge uncertainty",
                "gold_key_points_coverage": 0.5,
                "answer_text": "Recommendation:\nAcknowledge uncertainty and escalate for review.",
            }
        )
    write_flagged_jsonl(results_dir / "flagged_cases.jsonl", flagged_rows)


class ReviewerReportTests(unittest.TestCase):
    def test_load_report_data_parses_artifacts_and_counts_review_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results_dir = Path(tmpdir) / "results"
            create_artifacts(results_dir)

            data = load_report_data(str(results_dir))

            self.assertEqual(data.grade_counts["PASS"], 1)
            self.assertEqual(data.grade_counts["WARN"], 1)
            self.assertEqual(data.failure_tag_counts["UNCERTAINTY_MISALIGNED"], 1)
            self.assertEqual(len(data.flagged_cases), 1)
            self.assertEqual(len(data.all_cases), 2)
            self.assertEqual(
                [artifact["filename"] for artifact in data.source_artifacts],
                [
                    "run_manifest.json",
                    "evaluation_output.csv",
                    "flagged_cases.jsonl",
                    "summary.md",
                    "raw_generations.jsonl",
                ],
            )
            flagged = data.flagged_cases[0]
            self.assertEqual(flagged["case_id"], "SAFE_B")
            self.assertEqual(flagged["provider"], "mock")
            self.assertEqual(flagged["scores"]["faithfulness_proxy"], "0.5")
            self.assertEqual(flagged["review_rank"], 1)
            self.assertIn("orientation metric", flagged["review_priority_reason"])

    def test_supporting_metric_display_label_is_not_grade_driving(self) -> None:
        label = format_metric({"metric": "gold_key_points_coverage", "value": 0.5})

        self.assertEqual(label, "gold_key_points_coverage (supporting; not grade-driving)=0.500")

    def test_load_report_data_rejects_flagged_overlap_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results_dir = Path(tmpdir) / "results"
            create_artifacts(results_dir, flagged_failure_tags="DIFFERENT_TAG")

            with self.assertRaisesRegex(ValueError, "failure_tags"):
                load_report_data(str(results_dir))

    def test_report_generation_writes_self_contained_package_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            results_dir = tmp_path / "results"
            output_dir = tmp_path / "reviewer_package"
            create_artifacts(results_dir)

            written_paths = write_reviewer_package(
                results_dir=str(results_dir),
                output_dir=str(output_dir),
            )

            self.assertEqual(written_paths.package_dir, output_dir)
            self.assertEqual(written_paths.html_path, output_dir / "reviewer_report.html")
            self.assertEqual(written_paths.json_path, output_dir / "reviewer_summary.json")
            report_html = written_paths.html_path.read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", report_html)
            self.assertIn("Derived / non-canonical", report_html)
            self.assertIn("Run Summary", report_html)
            self.assertIn("Source Artifacts", report_html)
            self.assertIn("Grade Distribution", report_html)
            self.assertIn("Metric Score Summary", report_html)
            self.assertIn("Failure Categories And Flags", report_html)
            self.assertIn("Review First", report_html)
            self.assertIn("Full Case Index", report_html)
            self.assertIn("Flagged Case Details", report_html)
            self.assertIn("Validated Artifact Overlap", report_html)
            self.assertIn("Canonical Sources Of Truth", report_html)
            self.assertIn("not a severity label", report_html)
            self.assertIn("Orientation metric", report_html)
            self.assertNotIn("Lowest displayed metric", report_html)
            self.assertIn("gold_key_points_coverage (supporting; not grade-driving)", report_html)
            self.assertIn("SAFE_B", report_html)
            self.assertIn("What should happen when evidence is limited?", report_html)

            summary = json.loads(written_paths.json_path.read_text(encoding="utf-8"))
            self.assertTrue(summary["package"]["derived_non_canonical"])
            self.assertEqual(summary["package"]["schema_version"], "reviewer-package-v1")
            self.assertIn("does not rescore cases", summary["package"]["disclaimer"])
            self.assertEqual(summary["validation"]["status"], "passed")
            self.assertEqual(summary["headline_results"]["total_cases"], 2)
            self.assertEqual(summary["headline_results"]["flagged_cases"], 1)
            self.assertEqual(summary["review_first_cases"][0]["case_id"], "SAFE_B")
            self.assertEqual(summary["canonical_source_guidance"]["full_scored_table"], "evaluation_output.csv")
            metric_summary = {item["metric"]: item for item in summary["metric_summary"]}
            self.assertEqual(
                metric_summary["gold_key_points_coverage"]["display_name"],
                "gold_key_points_coverage (supporting; not grade-driving)",
            )
            self.assertEqual(
                metric_summary["gold_key_points_coverage"]["interpretation_note"],
                "supporting; not grade-driving",
            )
            for artifact in summary["source_artifacts"]:
                self.assertTrue(artifact["present"], artifact["filename"])
                self.assertIsInstance(artifact["bytes"], int)
                self.assertEqual(len(artifact["sha256"]), 64)
                self.assertTrue(artifact["relative_link_from_package"], artifact["filename"])

            canonical_manifest = Path(__file__).resolve().parents[1] / "results" / "run_manifest.json"
            with self.assertRaisesRegex(ValueError, "cannot overwrite canonical artifact"):
                write_reviewer_package(
                    results_dir=str(results_dir),
                    html_output_path=str(canonical_manifest),
                )

    def test_default_package_dir_is_outside_source_results_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            results_dir = tmp_path / "results"
            create_artifacts(results_dir)

            written_paths = write_reviewer_package(results_dir=str(results_dir))

            self.assertEqual(written_paths.package_dir.parent, tmp_path / "reviewer_packages")
            self.assertEqual(written_paths.package_dir.name, "mock_mock-clinical-model_unit-run")
            self.assertTrue(written_paths.html_path.exists())
            self.assertTrue(written_paths.json_path.exists())
            summary = json.loads(written_paths.json_path.read_text(encoding="utf-8"))
            by_filename = {artifact["filename"]: artifact for artifact in summary["source_artifacts"]}
            self.assertEqual(
                by_filename["run_manifest.json"]["relative_link_from_package"],
                "../../results/run_manifest.json",
            )

    def test_report_generation_fails_when_completed_run_source_artifact_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results_dir = Path(tmpdir) / "results"
            create_artifacts(results_dir)
            (results_dir / "summary.md").unlink()

            with self.assertRaisesRegex(FileNotFoundError, "summary.md"):
                load_report_data(str(results_dir))

    def test_zero_flagged_cases_still_renders_valid_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            results_dir = tmp_path / "results"
            output_dir = tmp_path / "reviewer_package"
            create_artifacts(
                results_dir,
                include_flagged_case=False,
                second_grade="PASS",
                second_failure_tags="",
            )

            written_paths = write_reviewer_package(results_dir=str(results_dir), output_dir=str(output_dir))

            report_html = written_paths.html_path.read_text(encoding="utf-8")
            summary = json.loads(written_paths.json_path.read_text(encoding="utf-8"))
            self.assertIn("No WARN or FAIL cases were present in flagged_cases.jsonl.", report_html)
            self.assertEqual(summary["headline_results"]["flagged_cases"], 0)
            self.assertEqual(summary["review_first_cases"], [])
            self.assertEqual(summary["flagged_case_details"], [])

    def test_report_generation_fails_when_raw_generations_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results_dir = Path(tmpdir) / "results"
            create_artifacts(results_dir)
            (results_dir / "raw_generations.jsonl").unlink()

            with self.assertRaisesRegex(FileNotFoundError, "raw_generations.jsonl"):
                load_report_data(str(results_dir))

    def test_report_generation_fails_on_malformed_flagged_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results_dir = Path(tmpdir) / "results"
            create_artifacts(results_dir)
            (results_dir / "flagged_cases.jsonl").write_text("{not json\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Invalid JSON in flagged_cases.jsonl line 1"):
                load_report_data(str(results_dir))

    def test_report_generation_fails_when_evaluation_required_column_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results_dir = Path(tmpdir) / "results"
            create_artifacts(results_dir)
            with (results_dir / "evaluation_output.csv").open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "case_id",
                        "run_id",
                        "provider",
                        "model_id",
                        "prompt_version",
                        "overall_grade",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "case_id": "SAFE_A",
                        "run_id": "unit-run",
                        "provider": "mock",
                        "model_id": "mock-clinical-model",
                        "prompt_version": "test-v1",
                        "overall_grade": "PASS",
                    }
                )

            with self.assertRaisesRegex(ValueError, "missing required columns: failure_tags"):
                load_report_data(str(results_dir))

    def test_custom_output_dir_source_links_are_relative_to_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            results_dir = tmp_path / "runs" / "completed"
            output_dir = tmp_path / "packages" / "custom-review"
            create_artifacts(results_dir)

            written_paths = write_reviewer_package(results_dir=str(results_dir), output_dir=str(output_dir))

            summary = json.loads(written_paths.json_path.read_text(encoding="utf-8"))
            by_filename = {artifact["filename"]: artifact for artifact in summary["source_artifacts"]}
            self.assertEqual(
                by_filename["run_manifest.json"]["relative_link_from_package"],
                "../../runs/completed/run_manifest.json",
            )
            self.assertEqual(
                by_filename["raw_generations.jsonl"]["relative_link_from_package"],
                "../../runs/completed/raw_generations.jsonl",
            )


if __name__ == "__main__":
    unittest.main()
