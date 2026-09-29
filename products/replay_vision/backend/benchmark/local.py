"""A local copy of one built benchmark version, which the eval suite reads.

`pull_version` copies a tier of built cases out of the benchmark bucket. The copy holds session recordings and
analytics events, so it expires: `LocalBenchmark.load` refuses a copy older than `LOCAL_COPY_MAX_AGE`, and a
fresh pull replaces it.
"""

import json
import datetime as dt
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from posthog.temporal.session_replay.rasterize_recording.types import RasterizationActivityOutput

from products.replay_vision.backend.benchmark.labels import Cell, Question
from products.replay_vision.backend.benchmark.layout import (
    FAST_TIER_SIZE,
    BenchmarkCase,
    BenchmarkLayout,
    sample_case_ids,
)
from products.replay_vision.backend.temporal.types import ScannerLlmInputs

Tier = Literal["fast", "full"]

LOCAL_COPY_MAX_AGE = dt.timedelta(days=30)
_PULL_RECORD = "pulled.json"
_VIDEO_FILE = "video.mp4"


class PullRecord(BaseModel, frozen=True):
    version: str
    tier: Tier
    pulled_at: dt.datetime
    case_ids: list[str]


class LocalBenchmark:
    def __init__(self, root: Path, record: PullRecord) -> None:
        self.root = root
        self.record = record
        self.questions = {
            question.question_id: question
            for question in (Question.model_validate(q) for q in json.loads((root / "questions.json").read_text()))
        }
        cases = {
            case.case_id: case
            for case in (BenchmarkCase.model_validate_json(line) for line in _lines(root / "cases.jsonl"))
        }
        self.cases = [cases[case_id] for case_id in record.case_ids]
        pulled = set(record.case_ids)
        self.cells = [
            cell
            for cell in (Cell.model_validate_json(line) for line in _lines(root / "labels.jsonl"))
            if cell.recording_id in pulled
        ]

    @classmethod
    def load(cls, root: Path, now: dt.datetime) -> "LocalBenchmark":
        record = PullRecord.model_validate_json((root / _PULL_RECORD).read_text())
        if now - record.pulled_at > LOCAL_COPY_MAX_AGE:
            raise RuntimeError(
                f"The benchmark copy at {root} is older than {LOCAL_COPY_MAX_AGE.days} days; pull it again"
            )
        return cls(root, record)

    def inputs(self, case_id: str) -> ScannerLlmInputs:
        return ScannerLlmInputs.model_validate_json((self.root / "cases" / case_id / "inputs.json").read_text())

    def render(self, case_id: str) -> RasterizationActivityOutput:
        status = json.loads((self.root / "cases" / case_id / "status.json").read_text())
        return RasterizationActivityOutput.model_validate(status["render"])

    def video_path(self, case_id: str) -> Path:
        return self.root / "cases" / case_id / _VIDEO_FILE


def pull_version(s3: Any, layout: BenchmarkLayout, tier: Tier, dest: Path, now: dt.datetime) -> PullRecord:
    """Copy a built version's labels and one tier of its built cases into `dest`. `s3` is a boto3 S3 client."""
    if not _exists(s3, layout.bucket, layout.manifest_key):
        raise RuntimeError(f"{layout.root} has no manifest: the version is not built yet")
    for key, name in (
        (layout.manifest_key, "manifest.json"),
        (layout.questions_key, "questions.json"),
        (layout.labels_key, "labels.jsonl"),
        (layout.cases_key, "cases.jsonl"),
    ):
        _download(s3, layout.bucket, key, dest / name)

    renders: dict[str, RasterizationActivityOutput] = {}
    for line in _lines(dest / "cases.jsonl"):
        case_id = BenchmarkCase.model_validate_json(line).case_id
        status = json.loads(_read(s3, layout.bucket, layout.status_key(case_id)) or "{}")
        if status.get("outcome") == "built" and status.get("render"):
            renders[case_id] = RasterizationActivityOutput.model_validate(status["render"])

    case_ids = sample_case_ids(renders, FAST_TIER_SIZE) if tier == "fast" else sorted(renders)
    for case_id in case_ids:
        case_dir = dest / "cases" / case_id
        _download(s3, layout.bucket, layout.inputs_key(case_id), case_dir / "inputs.json")
        _download(s3, layout.bucket, layout.status_key(case_id), case_dir / "status.json")
        video_bucket, video_key = renders[case_id].s3_uri.removeprefix("s3://").split("/", 1)
        _download(s3, video_bucket, video_key, case_dir / _VIDEO_FILE)

    # Written last, so an interrupted pull leaves no record for the suite to trust.
    record = PullRecord(version=layout.root.rsplit("/", 1)[-1], tier=tier, pulled_at=now, case_ids=case_ids)
    (dest / _PULL_RECORD).write_text(record.model_dump_json())
    return record


def _lines(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if line.strip()]


def _exists(s3: Any, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except s3.exceptions.ClientError as error:
        if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise
    return True


def _read(s3: Any, bucket: str, key: str) -> str | None:
    try:
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode()
    except s3.exceptions.NoSuchKey:
        return None


def _download(s3: Any, bucket: str, key: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(bucket, key, str(path))
