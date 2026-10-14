"""Credential and bounded-input regressions; no provider requests are sent."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch

import requests

from src.generate_answers import main as generate
from src.llm_clients import AnthropicClient, GeminiClient, LLMGenerationError, OpenAIClient
from src.metrics import MAX_ANSWER_CHARS, evaluate_case, extract_citations, extract_context_anchors

ROOT = Path(__file__).resolve().parents[1]


class CredentialTests(unittest.TestCase):
    def test_transport_errors_and_generation_logs_do_not_disclose_credentials(self):
        sentinel = "AUDIT_SENTINEL_CREDENTIAL_NOT_REAL"
        credentials = {"OPENAI_API_KEY": sentinel, "ANTHROPIC_API_KEY": sentinel,
                       "GEMINI_API_KEY": sentinel}
        with patch.dict(os.environ, credentials):
            for cls in (OpenAIClient, AnthropicClient, GeminiClient):
                with self.subTest(provider=cls.__name__):
                    client = cls(max_retries=1)
                    with patch("src.llm_clients.requests.post", side_effect=requests.ConnectionError(
                            f"Injected connection error: ?key={sentinel}; Authorization: {sentinel}")) as post:
                        try:
                            client.generate("test")
                        except LLMGenerationError as exc:
                            self.assertNotIn(sentinel, "".join(traceback.format_exception(exc)))
                        else:
                            self.fail("Connection error must propagate as a sanitized failure")
                    self.assertNotIn(sentinel, post.call_args.args[0])
                    if cls is GeminiClient:
                        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], sentinel)
            output = io.StringIO()
            with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(output), \
                    patch("src.llm_clients.requests.post", side_effect=requests.ConnectionError(sentinel)):
                with self.assertRaises(LLMGenerationError) as caught:
                    generate(str(ROOT / "dataset/clinical_questions.csv"), "gemini", "gemini-3.8-flash",
                             "v1", "secret-test", 1, 0, tmp)
                self.assertNotIn(sentinel, str(caught.exception))
            self.assertNotIn(sentinel, output.getvalue())

    def test_http_error_bodies_are_not_logged(self):
        sentinel = "AUDIT_SENTINEL_RESPONSE_KEY_NOT_REAL"
        response = requests.Response()
        response.status_code = 403
        response._content = ('{"error": "' + sentinel + '"}').encode()
        with patch.dict(os.environ, {"GEMINI_API_KEY": sentinel}), \
                patch("src.llm_clients.requests.post", return_value=response):
            with self.assertRaises(LLMGenerationError) as caught:
                GeminiClient(max_retries=1).generate("test")
        self.assertNotIn(sentinel, str(caught.exception))


class BoundedInputTests(unittest.TestCase):
    def test_oversized_answer_fails_before_any_other_scoring(self):
        with patch("src.metrics.extract_context_anchors", side_effect=AssertionError("scoring started")):
            result = evaluate_case("x" * (MAX_ANSWER_CHARS + 1), "", "answer", [], [])
        self.assertEqual(result.failure_tags, ["OVERSIZED_ANSWER"])
        self.assertEqual(result.scores["overall_grade"], "FAIL")
        self.assertTrue(all(value is None for key, value in result.scores.items() if key != "overall_grade"))
        # Exactly the documented maximum remains eligible for normal scoring.
        evaluate_case("x" * MAX_ANSWER_CHARS, "", "answer", [], [])

    def test_oversized_answer_can_never_pass_or_warn(self):
        for expected in ("answer", "refuse", "uncertain"):
            for status in ("complete", "incomplete"):
                with self.subTest(expected=expected, status=status):
                    result = evaluate_case("[CTX999] prescribe amoxicillin " * MAX_ANSWER_CHARS,
                                           "CTX1: Context.", expected, ["CTX1"],
                                           ["prescribe amoxicillin"], ["context"], status)
                    self.assertEqual(result.scores["overall_grade"], "FAIL")
                    self.assertEqual(result.failure_tags, ["OVERSIZED_ANSWER"])

    def test_citation_deduplication_preserves_first_seen_order(self):
        self.assertEqual(extract_citations("[CTX2] [CTX1] [CTX2]"), ["CTX2", "CTX1"])
        self.assertEqual(extract_context_anchors("CTX2: a CTX1: b CTX2: c"), ["CTX2", "CTX1"])

    def test_adversarial_input_processing_finishes_within_five_seconds(self):
        # Process timeout bounds even a regression that would hang the test runner.
        program = """
from src.metrics import MAX_ANSWER_CHARS, evaluate_case, extract_citations, extract_context_anchors
result = evaluate_case('Do not prescribe amoxicillin. ' * 100_000, '', 'answer', [], [])
assert result.scores['overall_grade'] == 'FAIL'
assert result.failure_tags == ['OVERSIZED_ANSWER']
assert all(v is None for k, v in result.scores.items() if k != 'overall_grade')
assert len(extract_citations(' '.join('[CTX%d]' % i for i in range(100_000)))) == 100_000
assert len(extract_context_anchors(' '.join('CTX%d:' % i for i in range(100_000)))) == 100_000
"""
        subprocess.run([sys.executable, "-c", program], cwd=ROOT, check=True,
                       capture_output=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
