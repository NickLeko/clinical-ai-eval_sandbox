from dataclasses import dataclass
from pathlib import Path


CACHE_DIRNAME = "cache"
PUBLIC_RAW_FILENAME = "raw_generations.jsonl"
CACHE_RAW_FILENAME = "raw_generations_cache.jsonl"
RUN_MANIFEST_FILENAME = "run_manifest.json"
EVALUATION_OUTPUT_FILENAME = "evaluation_output.csv"
FLAGGED_OUTPUT_FILENAME = "flagged_cases.jsonl"
SUMMARY_OUTPUT_FILENAME = "summary.md"
EVALUATION_MANIFEST_FILENAME = "evaluation_manifest.json"


@dataclass(frozen=True)
class ArtifactPaths:
    results_dir: Path
    cache_dir: Path
    public_raw_path: Path
    cache_raw_path: Path
    run_manifest_path: Path
    evaluation_output_path: Path
    flagged_output_path: Path
    summary_output_path: Path
    evaluation_manifest_path: Path


def build_artifact_paths(results_dir: str = "results") -> ArtifactPaths:
    results_root = Path(results_dir)
    cache_dir = results_root / CACHE_DIRNAME

    return ArtifactPaths(
        results_dir=results_root,
        cache_dir=cache_dir,
        public_raw_path=results_root / PUBLIC_RAW_FILENAME,
        cache_raw_path=cache_dir / CACHE_RAW_FILENAME,
        run_manifest_path=results_root / RUN_MANIFEST_FILENAME,
        evaluation_output_path=results_root / EVALUATION_OUTPUT_FILENAME,
        flagged_output_path=results_root / FLAGGED_OUTPUT_FILENAME,
        summary_output_path=results_root / SUMMARY_OUTPUT_FILENAME,
        evaluation_manifest_path=results_root / EVALUATION_MANIFEST_FILENAME,
    )
