"""Golden-dataset layout shared by the collector (collect.py) and the eval suite.

A dataset is a plain directory, never committed to the repo (it contains real session data):

    manifest.json                  # GoldenDataset
    cases/<case_id>/video.mp4      # rasterized recording, byte-identical to what production sent to Gemini
    cases/<case_id>/inputs.json    # ScannerLlmInputs snapshot (events table, session metadata, navigation)
"""

import os
import datetime as dt
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from products.replay_vision.backend.temporal.types import ScannerLlmInputs, ScannerSnapshot

DATASET_ENV_VAR = "REPLAY_VISION_EVAL_DATASET"
MANIFEST_NAME = "manifest.json"
VIDEO_NAME = "video.mp4"
INPUTS_NAME = "inputs.json"
# Production re-checks AI data-processing consent right before every generation; for the eval the only
# check happens when collect.py runs, so bound how long that verification (and the collected recordings
# themselves) may be trusted.
DATASET_MAX_AGE_DAYS = 30


def parse_utc(raw: Any) -> dt.datetime:
    """Parse an ISO timestamp into UTC; a naive string would silently shift by this machine's timezone, so reject it."""
    parsed = dt.datetime.fromisoformat(str(raw))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {raw!r} has no timezone; expected an offset-aware ISO string")
    return parsed.astimezone(dt.UTC)


class GoldenCase(BaseModel, frozen=True):
    """One collected observation: the frozen scanner config, its recorded output, and the human label if any."""

    case_id: str = Field(description="Source ReplayObservation id; doubles as the case directory name.")
    scanner_id: str
    scanner_name: str
    scanner_type: str
    session_id: str
    team_id: int
    team_name: str
    snapshot: ScannerSnapshot
    recorded_output: dict[str, Any] = Field(description="scanner_result.model_output at collection time.")
    known_freeform_tags: list[str] = Field(
        default_factory=list,
        description="Tag vocabulary a freeform classifier scans with, captured at collection time.",
    )
    label_is_correct: bool | None = None
    label_feedback: str = ""
    collected_at: str

    def case_dir(self, root: Path) -> Path:
        return root / "cases" / self.case_id

    def video_path(self, root: Path) -> Path:
        return self.case_dir(root) / VIDEO_NAME

    def inputs_path(self, root: Path) -> Path:
        return self.case_dir(root) / INPUTS_NAME

    def load_inputs(self, root: Path) -> ScannerLlmInputs:
        return ScannerLlmInputs.model_validate_json(self.inputs_path(root).read_text())


class GoldenDataset(BaseModel, frozen=True):
    created_at: str
    host: str
    project_id: int
    cases: list[GoldenCase] = Field(default_factory=list)


def dataset_root() -> Path | None:
    raw = os.environ.get(DATASET_ENV_VAR, "").strip()
    return Path(raw).expanduser() if raw else None


def load_dataset(root: Path) -> GoldenDataset:
    return GoldenDataset.model_validate_json((root / MANIFEST_NAME).read_text())


def ensure_dataset_fresh(dataset: GoldenDataset, root: Path) -> None:
    """Refuse to scan a dataset whose consent verification has lapsed (see DATASET_MAX_AGE_DAYS)."""
    age = dt.datetime.now(dt.UTC) - parse_utc(dataset.created_at)
    if age > dt.timedelta(days=DATASET_MAX_AGE_DAYS):
        raise RuntimeError(
            f"Dataset at {root} was collected {age.days} days ago (limit {DATASET_MAX_AGE_DAYS}); "
            "re-run collect.py, which re-verifies AI data-processing consent"
        )


def save_dataset(root: Path, dataset: GoldenDataset) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST_NAME).write_text(dataset.model_dump_json(indent=2))
