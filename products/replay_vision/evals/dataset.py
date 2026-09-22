"""Golden-dataset layout shared by the collector (collect.py) and the eval suite.

A dataset is a plain directory, never committed to the repo (it contains real session data):

    manifest.json                  # GoldenDataset
    cases/<case_id>/video.mp4      # rasterized recording, byte-identical to what production sent to Gemini
    cases/<case_id>/inputs.json    # ScannerLlmInputs snapshot (events table, session metadata, navigation)

A dataset can also be pinned in object storage (see `upload_pinned_dataset` /
`download_pinned_dataset`), so prompt PRs compare against the same footage every run instead of a
re-sampled fresh collection. The set is fixed by convention: a person curates and uploads it, and
CI reads it unchanged. Consent is re-verified via the source instance's API at eval start.
"""

import os
import datetime as dt
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from posthog.dataclasses import frozen

from products.replay_vision.backend.temporal.types import ScannerLlmInputs, ScannerSnapshot

DATASET_ENV_VAR = "REPLAY_VISION_EVAL_DATASET"
DATASET_BUCKET_ENV_VAR = "REPLAY_VISION_EVAL_DATASET_BUCKET"
DATASET_KEY_ENV_VAR = "REPLAY_VISION_EVAL_DATASET_OBJECT_KEY"
MANIFEST_NAME = "manifest.json"
VIDEO_NAME = "video.mp4"
INPUTS_NAME = "inputs.json"


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
    inactivity_periods: list[dict[str, Any]] = Field(
        default_factory=list,
        description="The rendered video's active/inactive map, for converting the model's video-time citations. "
        "Empty on cases collected before it was captured, which then score as if nothing was cut.",
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
    # For the consent re-check at eval time. Optional so manifests collected before it was recorded
    # still load; those fall back to the organization endpoint with the project id.
    organization_id: int | None = None
    cases: list[GoldenCase] = Field(default_factory=list)


def dataset_root() -> Path | None:
    raw = os.environ.get(DATASET_ENV_VAR, "").strip()
    return Path(raw).expanduser() if raw else None


def load_dataset(root: Path) -> GoldenDataset:
    return GoldenDataset.model_validate_json((root / MANIFEST_NAME).read_text())


def ensure_dataset_consent(dataset: GoldenDataset, api_key: str) -> None:
    """Re-verify the source org's AI data-processing consent, fresh, before scanning a dataset.

    Age is the wrong gate for a pinned dataset: the pin outlives any age window by design, and the
    thing age proxied for is consent, which is checked directly here. Runs against the source
    instance's public API so it works from any runner, fail-closed on any error.
    """
    import requests  # noqa: PLC0415 - keeps requests off the module import path of pure consumers

    if not api_key:
        raise RuntimeError("Set POSTHOG_API_KEY so the dataset's source-org consent can be re-verified")
    headers = {"Authorization": f"Bearer {api_key}"}
    organization_id = dataset.organization_id
    if organization_id is None:
        # Older manifests predate the recorded org id; resolve it through the project endpoint.
        environment = requests.get(
            f"{dataset.host}/api/environments/{dataset.project_id}/", headers=headers, timeout=60
        )
        environment.raise_for_status()
        organization_id = int(environment.json()["organization"])
    organization = requests.get(f"{dataset.host}/api/organizations/{organization_id}/", headers=headers, timeout=60)
    organization.raise_for_status()
    if not organization.json().get("is_ai_data_processing_approved"):
        raise RuntimeError(
            "The dataset's source organization has withdrawn AI data-processing consent; "
            "the eval must not scan its recordings"
        )


def save_dataset(root: Path, dataset: GoldenDataset) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST_NAME).write_text(dataset.model_dump_json(indent=2))


def _case_key(key: str, case_id: str, file_name: str) -> str:
    """Object key of one case file; `key` is the manifest key, the case files sit beside it."""
    return f"{key.rsplit('/', 1)[0]}/cases/{case_id}/{file_name}"


@frozen
class _DatasetObjectLocation:
    """Where the pin lives in object storage; named fields so bucket and key cannot be swapped."""

    bucket: str
    key: str


def _bucket_and_key(bucket: str | None, key: str | None) -> _DatasetObjectLocation:
    raw_bucket = bucket if bucket is not None else os.environ.get(DATASET_BUCKET_ENV_VAR, "").strip()
    raw_key = key if key is not None else os.environ.get(DATASET_KEY_ENV_VAR, "").strip()
    if not raw_bucket or not raw_key:
        raise RuntimeError(
            f"Set {DATASET_BUCKET_ENV_VAR} and {DATASET_KEY_ENV_VAR} (or pass bucket/key explicitly) "
            "to use the pinned golden dataset"
        )
    return _DatasetObjectLocation(bucket=raw_bucket, key=raw_key)


def upload_pinned_dataset(
    root: Path, dataset: GoldenDataset, *, bucket: str | None = None, key: str | None = None
) -> None:
    """Upload the manifest and every case's video and inputs under the dataset's object-storage key.

    Writes everything it is given, so an upload replaces whatever the key held. The set is fixed by
    convention: a person uploads a curated dataset once and CI reads it unchanged; growing it is a
    deliberate re-upload, never an automatic step. The manifest lands last, so a reader never sees
    a manifest naming cases whose bytes are absent.
    """
    from posthog.storage import object_storage  # noqa: PLC0415 - keeps boto3/Django off the eval import path

    location = _bucket_and_key(bucket, key)
    missing = [g.case_id for g in dataset.cases if not (g.video_path(root).exists() and g.inputs_path(root).exists())]
    if missing:
        raise RuntimeError(f"Dataset at {root} is missing files for cases {missing[:5]}; collect before uploading")
    for golden in dataset.cases:
        object_storage.write_from_file(
            _case_key(location.key, golden.case_id, VIDEO_NAME), str(golden.video_path(root)), bucket=location.bucket
        )
        object_storage.write(
            _case_key(location.key, golden.case_id, INPUTS_NAME),
            golden.inputs_path(root).read_bytes(),
            bucket=location.bucket,
        )
    object_storage.write(location.key, dataset.model_dump_json(indent=2), bucket=location.bucket)


def download_pinned_dataset(root: Path, *, bucket: str | None = None, key: str | None = None) -> GoldenDataset:
    """Download the pinned dataset into root, skipping cases whose bytes are already on disk.

    A re-run costs nothing for the part already local, so CI runners can cache nothing and still
    only pay for what a fresh runner needs.
    """
    from posthog.storage import object_storage  # noqa: PLC0415 - keeps boto3/Django off the eval import path

    location = _bucket_and_key(bucket, key)
    raw = object_storage.read_bytes(location.key, bucket=location.bucket)
    if raw is None:
        raise RuntimeError(f"No pinned golden dataset at s3://{location.bucket}/{location.key}")
    dataset = GoldenDataset.model_validate_json(raw)
    root.mkdir(parents=True, exist_ok=True)
    save_dataset(root, dataset)
    for golden in dataset.cases:
        if golden.video_path(root).exists() and golden.inputs_path(root).exists():
            continue
        golden.case_dir(root).mkdir(parents=True, exist_ok=True)
        video = object_storage.read_bytes(
            _case_key(location.key, golden.case_id, VIDEO_NAME), bucket=location.bucket, missing_ok=True
        )
        if video is None:
            raise RuntimeError(f"Pinned dataset is missing video for case {golden.case_id}")
        golden.video_path(root).write_bytes(video)
        inputs = object_storage.read_bytes(
            _case_key(location.key, golden.case_id, INPUTS_NAME), bucket=location.bucket, missing_ok=True
        )
        if inputs is None:
            raise RuntimeError(f"Pinned dataset is missing inputs for case {golden.case_id}")
        golden.inputs_path(root).write_text(inputs.decode())
    return dataset
