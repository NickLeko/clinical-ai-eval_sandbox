"""Adversarial artifact/provider regressions using completed offline harness runs."""
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src import generate_answers as generation
from src import run_evaluation as evaluation
from src import summarize_results as summary
from src.artifact_integrity import validate_scored_artifacts
from src.build_reviewer_report import load_report_data
from src.llm_clients import (OpenAIClient, AnthropicClient, GeminiClient, MockClient,
                             validate_generation_payload)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset/clinical_questions.csv"


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


class ReleaseIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.base_tmp.name) / "run"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            generation.main(str(DATASET), "mock", "mock", "v1", "integrity-test", None, 0, str(cls.base))
            evaluation.main(str(DATASET), str(cls.base))
            summary.main(10, str(cls.base))

    @classmethod
    def tearDownClass(cls):
        cls.base_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / "run"
        shutil.copytree(self.base, self.run)

    def assert_views_reject(self):
        for function in [lambda: summary.main(10, str(self.run)), lambda: load_report_data(str(self.run))]:
            with self.assertRaises((ValueError, FileNotFoundError)):
                function()

    def test_completed_run_and_summary_are_bound(self):
        receipt = validate_scored_artifacts(self.run, require_summary=True)
        self.assertEqual(receipt["acceptance"]["status"], "PASS")
        self.assertGreater(receipt["acceptance"]["tests_run"], 300)
        self.assertEqual(len(load_report_data(str(self.run)).all_cases), 25)

    def test_extra_raw_fields_cannot_shadow_any_dataset_rule(self):
        path = self.run / "raw_generations.jsonl"
        original = read_rows(path)
        for field in ["question", "provided_context", "expected_behavior", "forbidden_actions",
                      "required_citations", "gold_key_points", "category", "risk_level"]:
            rows = [dict(row) for row in original]
            rows[0][field] = ""
            write_rows(path, rows)
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "reserved dataset fields"):
                    evaluation.main(str(DATASET), str(self.run))

    def test_corrupt_cache_answer_is_rejected_before_replay(self):
        path = self.run / "cache/raw_generations_cache.jsonl"
        rows = read_rows(path)
        rows[0]["answer_text"] = "An answer never returned by this provider."
        write_rows(path, rows)
        with self.assertRaisesRegex(ValueError, "contradicts raw_response"):
            generation.main(str(DATASET), "mock", "mock", "v1", "integrity-test", None, 0, str(self.run))

    def test_unscored_raw_text_rejected_by_both_views_and_evaluator(self):
        path = self.run / "raw_generations.jsonl"
        rows = read_rows(path)
        rows[0]["answer_text"] = "Prescribe amoxicillin."
        write_rows(path, rows)
        self.assert_views_reject()
        with self.assertRaisesRegex(ValueError, "contradicts raw_response"):
            evaluation.main(str(DATASET), str(self.run))

    def test_missing_receipt_is_unscored(self):
        (self.run / "evaluation_manifest.json").unlink()
        self.assert_views_reject()

    def test_missing_safety_columns_and_stale_csv_rejected(self):
        path = self.run / "evaluation_output.csv"
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            row["run_id"] = "another-run"
            del row["unsafe_recommendation"]
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self.assert_views_reject()

    def test_missing_flagged_rows_rejected(self):
        (self.run / "flagged_cases.jsonl").write_text("")
        self.assert_views_reject()

    def test_changed_summary_and_new_evaluation_require_resummary(self):
        (self.run / "summary.md").write_text("All cases PASS")
        with self.assertRaisesRegex(ValueError, "summary"):
            load_report_data(str(self.run))
        with contextlib.redirect_stdout(io.StringIO()):
            summary.main(10, str(self.run))
            evaluation.main(str(DATASET), str(self.run))
        with self.assertRaisesRegex(ValueError, "summary"):
            load_report_data(str(self.run))

    def test_wrong_prompt_key_and_prompt_version_rejected(self):
        path = self.run / "raw_generations.jsonl"
        original = read_rows(path)
        for field in ["prompt", "cache_key", "prompt_version"]:
            rows = [dict(row) for row in original]
            rows[0][field] = "wrong"
            write_rows(path, rows)
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    evaluation.main(str(DATASET), str(self.run))

    def test_stale_evaluator_and_acceptance_identity_rejected(self):
        path = self.run / "evaluation_manifest.json"
        original = json.loads(path.read_text())
        for field in ["evaluator", "acceptance"]:
            receipt = dict(original)
            receipt[field] = {}
            path.write_text(json.dumps(receipt))
            self.assert_views_reject()

    def test_incomplete_generation_is_fail_with_status_visible(self):
        path = self.run / "raw_generations.jsonl"
        rows = read_rows(path)
        for index, row in enumerate(rows):
            row.update(provider="openai", generation_status="incomplete" if index == 0 else "complete",
                       finish_reason="length" if index == 0 else "stop")
            row["raw_response"] = {"choices": [{"finish_reason": row["finish_reason"],
                                                 "message": {"content": row["answer_text"]}}]}
            row["cache_key"] = generation.build_cache_key(row["case_id"], "openai", row["model_id"],
                                                           row["prompt_version"], row["prompt"])
        write_rows(path, rows)
        manifest_path = self.run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["provider"] = "openai"
        manifest_path.write_text(json.dumps(manifest))
        with contextlib.redirect_stdout(io.StringIO()):
            evaluation.main(str(DATASET), str(self.run))
            summary.main(10, str(self.run))
        with (self.run / "evaluation_output.csv").open(newline="") as stream:
            first = next(csv.DictReader(stream))
        self.assertEqual(first["overall_grade"], "FAIL")
        self.assertEqual(first["generation_status"], "incomplete")
        self.assertIn("INCOMPLETE_GENERATION", first["failure_tags"])
        self.assertEqual(first["finish_reason"], "length")
        load_report_data(str(self.run))


class ProviderAndWorkflowTests(unittest.TestCase):
    def test_all_adapters_surface_complete_incomplete_and_unknown_status(self):
        text = MockClient().generate("")["answer_text"]
        fixtures = [
            ("openai", OpenAIClient, lambda reason: {"choices": [{"finish_reason": reason, "message": {"content": text}}]}, "stop", "length"),
            ("anthropic", AnthropicClient, lambda reason: {"stop_reason": reason, "content": [{"type": "text", "text": text}]}, "end_turn", "max_tokens"),
            ("gemini", GeminiClient, lambda reason: {"candidates": [{"finishReason": reason, "content": {"parts": [{"text": text}]}}]}, "STOP", "MAX_TOKENS"),
        ]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "ANTHROPIC_API_KEY": "test", "GEMINI_API_KEY": "test"}):
            for provider, cls, payload, complete, incomplete in fixtures:
                for reason in [complete, incomplete, None]:
                    with self.subTest(provider=provider, reason=reason):
                        client = cls()
                        with patch.object(client, "_post_json", return_value=payload(reason)):
                            response = client.generate("test")
                        status = "complete" if reason == complete else "incomplete"
                        self.assertEqual(response["generation_status"], status)
                        row = dict(response, provider=provider, model_id="test", case_id="test")
                        self.assertEqual(validate_generation_payload(row)["generation_status"], status)
                        row["generation_status"] = "forged"
                        with self.assertRaises(ValueError):
                            validate_generation_payload(row)

    def test_manual_input_is_data_and_not_shell_source(self):
        for name in ["eval.yml", "published_candidate.yml"]:
            text = (ROOT / ".github/workflows" / name).read_text()
            self.assertNotIn('--model "${{', text)
            self.assertNotIn('--run-id "${{', text)
            self.assertIn('"$INPUT_MODEL"', text)
        value = 'audit$(printf EXECUTED)`printf ALSO_EXECUTED`'
        completed = subprocess.run(["bash", "-c", 'printf "%s" "$INPUT_MODEL"'],
                                   env={**os.environ, "INPUT_MODEL": value}, capture_output=True, text=True, check=True)
        self.assertEqual(completed.stdout, value)


if __name__ == "__main__":
    unittest.main()
