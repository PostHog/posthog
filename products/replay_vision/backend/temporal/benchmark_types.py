"""Types for building a labeling benchmark version, split from `types.py` like `backfill_types.py`."""

from pydantic import BaseModel, Field

from products.replay_vision.backend.benchmark.layout import BenchmarkCase

# The prepare activity's error type for a session production would not scan, which the build skips.
BENCHMARK_CASE_SKIPPED_ERROR_TYPE = "BenchmarkCaseSkipped"


class BuildBenchmarkInputs(BaseModel, frozen=True):
    version: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    # Caps the snapshot to this many recordings, picked deterministically, for a small first version.
    recording_limit: int | None = Field(default=None, ge=1)
    # Renders in flight at once. Benchmark renders share the rasterizer with customer scans.
    max_concurrent_renders: int = Field(default=4, ge=1, le=16)
    # Carried across continue-as-new; unset on the first run, which takes the snapshot.
    case_count: int | None = None
    offset: int = 0
    built: int = 0
    failed: int = 0
    skipped: int = 0


class SnapshotBenchmarkInputs(BaseModel, frozen=True):
    version: str
    recording_limit: int | None = None


class SnapshotBenchmarkOutput(BaseModel, frozen=True):
    case_count: int
    cell_count: int


class LoadBenchmarkCasesInputs(BaseModel, frozen=True):
    version: str
    offset: int
    limit: int


class LoadBenchmarkCasesOutput(BaseModel, frozen=True):
    cases: list[BenchmarkCase]


class PrepareBenchmarkCaseInputs(BaseModel, frozen=True):
    version: str
    case: BenchmarkCase


class PrepareBenchmarkCaseOutput(BaseModel, frozen=True):
    source_s3_uri: str
    # Where the rasterizer writes the case's video.
    output_bucket: str
    output_prefix: str
    # Refs the recording carries, and images the export put back; the rest render as placeholders.
    image_refs: int
    images_resolved: int


class RecordBenchmarkCaseInputs(BaseModel, frozen=True):
    version: str
    case_id: str
    # The rasterizer's output (s3_uri, inactivity_periods, ...) on success, None on failure.
    render: dict | None = None
    error: str | None = None
    image_refs: int = 0
    images_resolved: int = 0
    # Why production would not scan the session, when it would not; a skipped case is neither built nor failed.
    skipped: str | None = None


class WriteBenchmarkManifestInputs(BaseModel, frozen=True):
    version: str
    case_count: int
    built: int
    failed: int
    skipped: int
