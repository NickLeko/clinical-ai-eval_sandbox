import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
REVIEWER_GUIDE_PATH = ROOT / "docs" / "reviewer_guide.md"
GITIGNORE_PATH = ROOT / ".gitignore"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ReviewerDocumentationTests(unittest.TestCase):
    def test_readme_preserves_scope_boundary_and_quick_path(self) -> None:
        readme = read_text(README_PATH)

        for required_text in [
            "This is a synthetic, demo-only evaluation sandbox.",
            "No PHI handling is implemented or claimed.",
            "No real patient data is included or expected.",
            "not for patient care",
            "## Quick Reviewer Path",
            "python -m pip install -r requirements.txt",
            "Dependency installation requires package-index access",
            "make verify",
            "--provider mock",
            "--results-dir sandbox_results/reviewer_smoke",
            "sandbox_results/reviewer_smoke/run_manifest.json",
            "results/run_manifest.json",
            "results/summary.md",
        ]:
            self.assertIn(required_text, readme)

    def test_readme_ties_trust_claims_to_concrete_evidence(self) -> None:
        readme = read_text(README_PATH)

        for required_text in [
            "## Evidence Trail For Reviewers",
            "results/raw_generations.jsonl",
            "dataset_sha256",
            "tests/test_artifact_consistency.py",
            "src/metrics.py",
            "tests/test_metrics.py",
            "src/llm_clients.py",
            "docs/REVIEWER_WORKFLOW.md",
        ]:
            self.assertIn(required_text, readme)

    def test_reviewer_guide_keeps_clone_to_inspect_workflow(self) -> None:
        guide = read_text(REVIEWER_GUIDE_PATH)

        for required_text in [
            "not a medical device",
            "not a PHI system",
            "python -m venv .venv",
            "python -m pip install -r requirements.txt",
            "Dependency installation requires package-index access",
            "make verify",
            "python src/generate_answers.py",
            "--run-kind sandbox",
            "sandbox_results/reviewer_smoke/evaluation_output.csv",
            "results/flagged_cases.jsonl",
            "reviewer_report.html",
            "derived convenience outputs only",
        ]:
            self.assertIn(required_text, guide)

    def test_generated_reviewer_paths_are_git_ignored(self) -> None:
        ignored_paths = set(read_text(GITIGNORE_PATH).splitlines())

        self.assertIn("sandbox_results/", ignored_paths)
        self.assertIn("reviewer_packages/", ignored_paths)


if __name__ == "__main__":
    unittest.main()
