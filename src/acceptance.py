"""Execute the blocking benchmark contract and return deterministic evidence."""
import hashlib
import io
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def contract_identity():
    names = ["dataset/clinical_questions.csv", "tests/test_adversarial_acceptance.py",
             "src/metrics.py", "src/acceptance.py", "src/llm_clients.py"]
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def run_contract():
    suite = unittest.TestLoader().discover(str(ROOT / "tests"), pattern="test_adversarial_acceptance.py")
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output).run(suite)
    if (not result.wasSuccessful() or result.testsRun == 0 or result.skipped
            or result.expectedFailures or result.unexpectedSuccesses):
        raise ValueError("Blocking adversarial acceptance suite failed:\n" + output.getvalue())
    return {"status": "PASS", "tests_run": result.testsRun, "failures": 0, "errors": 0,
            "skipped": 0, "expected_failures": 0, "identity": contract_identity()}


if __name__ == "__main__":
    print(json.dumps(run_contract(), indent=2))
