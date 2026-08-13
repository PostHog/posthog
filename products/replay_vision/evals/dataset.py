"""Golden-dataset layout shared by the collector (collect.py) and the eval suite.

A dataset is a plain directory, never committed to the repo (it contains real session data):

    manifest.json                  # GoldenDataset
    cases/<case_id>/video.mp4      # rasterized recording, byte-identical to what production sent to Gemini
    cases/<case_id>/inputs.json    # ScannerLlmInputs snapshot (events table, session metadata, navigation)
"""

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from products.replay_vision.backend.temporal.types import ScannerLlmInputs, ScannerSnapshot

DATASET_ENV_VAR = "REPLAY_VISION_EVAL_DATASET"
MANIFEST_NAME = "manifest.json"
VIDEO_NAME = "video.mp4"
INPUTS_NAME = "inputs.json"


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


def save_dataset(root: Path, dataset: GoldenDataset) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST_NAME).write_text(dataset.model_dump_json(indent=2))
