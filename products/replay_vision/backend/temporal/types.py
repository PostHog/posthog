import datetime as dt
from typing import Annotated, Any, TypedDict
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from products.replay_vision.backend.models.replay_observation import ObservationTrigger
from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.session_limits import MAX_SESSION_ID_LENGTH
from products.replay_vision.backend.temporal.scanners.base import SignalFinding
from products.replay_vision.backend.temporal.scanners.classifier import ClassifierOutput
from products.replay_vision.backend.temporal.scanners.monitor import MonitorOutput
from products.replay_vision.backend.temporal.scanners.scorer import ScorerOutput
from products.replay_vision.backend.temporal.scanners.summarizer import SummarizerOutput
from products.replay_vision.backend.temporal.snapshots import (
    BackfillScannerSnapshot as BackfillScannerSnapshot,
    ScannerSnapshot as ScannerSnapshot,
)

AnyScannerOutput = Annotated[
    ClassifierOutput | MonitorOutput | ScorerOutput | SummarizerOutput,
    Field(discriminator="scanner_type"),
]


class ScannerResult(BaseModel, frozen=True):
    """Result data of a completed observation, persisted into `ReplayObservation.scanner_result`."""

    model_output: AnyScannerOutput
    signals_count: int = Field(default=0, ge=0)


class ApplyScannerInputs(BaseModel, frozen=True):
    """Input to ApplyScannerWorkflow."""

    scanner_id: UUID
    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_LENGTH)
    team_id: int
    triggered_by: ObservationTrigger
    triggered_by_user_id: int | None = None
    # Set only for backfill-triggered applies; routes observation creation to the backfill's frozen snapshot.
    backfill_id: UUID | None = None


class CreateObservationInputs(BaseModel, frozen=True):
    scanner_id: UUID
    team_id: int
    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_LENGTH)
    triggered_by: ObservationTrigger
    triggered_by_user_id: int | None
    workflow_id: str
    backfill_id: UUID | None = None


class CreateObservationOutput(BaseModel, frozen=True):
    # `was_created=False` means no row was persisted (either the row already existed, or the org's monthly quota is exhausted); the caller should no-op.
    observation_id: UUID | None
    was_created: bool
    scanner_type: ScannerType


class MarkObservationRunningInputs(BaseModel, frozen=True):
    observation_id: UUID


# Coarse progress phases, surfaced live via ApplyScannerWorkflow's `get_progress` query and streamed over SSE.
OBSERVATION_PHASE_ORDER = ("queued", "fetching", "rendering", "uploading", "analyzing", "finalizing")
OBSERVATION_PHASE_INDEX = {phase: index for index, phase in enumerate(OBSERVATION_PHASE_ORDER)}


class ObservationProgress(TypedDict):
    """Live progress snapshot returned by ApplyScannerWorkflow's `get_progress` query, streamed to the client over SSE."""

    phase: str  # one of OBSERVATION_PHASE_ORDER
    step: int  # index of `phase` in OBSERVATION_PHASE_ORDER
    total_steps: int  # len(OBSERVATION_PHASE_ORDER)
    rasterizer_workflow_id: str | None  # set while rendering, so the stream can read the child's frame heartbeats


class MarkObservationFailedInputs(BaseModel, frozen=True):
    observation_id: UUID
    # `kind:message` — kind is one of FailureKind values.
    error_reason: str
    scanner_type: ScannerType


class MarkObservationIneligibleInputs(BaseModel, frozen=True):
    observation_id: UUID
    # `kind:message` — kind is one of IneligibleSessionKind values.
    error_reason: str
    scanner_type: ScannerType


class FetchSessionEventsInputs(BaseModel, frozen=True):
    observation_id: UUID
    team_id: int
    session_id: str


class EventTable(BaseModel, frozen=True):
    """A column-oriented analytics-event table; every row's arity matches `len(columns)`."""

    columns: list[str]
    rows: list[list[Any]]

    @model_validator(mode="after")
    def _rows_match_columns(self) -> "EventTable":
        column_count = len(self.columns)
        for index, row in enumerate(self.rows):
            if len(row) != column_count:
                raise ValueError(f"rows[{index}] has {len(row)} values but columns has {column_count}")
        return self

    def as_dicts(self) -> list[dict[str, Any]]:
        """Zip columns and rows into per-event dicts for prompt-template rendering; drops null/empty values so sparse events render compactly."""
        # Explicit `is None` (not membership) so 0/False are never dropped via `0 == False`.
        return [
            {
                column: value
                for column, value in zip(self.columns, row)
                if value is not None and value != "" and value != [] and value != {}
            }
            for row in self.rows
        ]


class SessionMetadata(BaseModel, frozen=True):
    """Session-level context exposed to the LLM prompt."""

    start_time: dt.datetime
    end_time: dt.datetime
    duration_seconds: float
    # ClickHouse derives these from `sum(active_milliseconds)/1000`, so they're floats in practice (e.g. 30.5s).
    active_seconds: float | None = None
    inactive_seconds: float | None = None
    click_count: int | None = None
    keypress_count: int | None = None
    mouse_activity_count: int | None = None
    start_url: str | None = None
    console_error_count: int | None = None

    def as_prompt_dict(self) -> dict[str, Any]:
        """Drop unset (None) fields so the prompt isn't padded with `null`s."""
        return self.model_dump(mode="json", exclude_none=True)


class NavigationEntry(BaseModel, frozen=True):
    """One page-URL change in the session, precomputed for the prompt's navigation timeline."""

    rec_t: int = Field(ge=0)
    # Interned `window_N` token, matching what the events tool returns. None when the session has no window ids.
    window: str | None = None
    url: str
    # First entry seen for a window token other than the session's initial one (a tab or window opening).
    new_window: bool = False


class ScannerLlmInputs(BaseModel, frozen=True):
    """Per-session analytics events + recording metadata, stashed in Redis between activities."""

    session_id: str
    team_id: int
    events: EventTable
    # Reverse mappings: `url_1` -> actual URL, `window_1` -> actual window UUID.
    url_mapping: dict[str, str] = Field(default_factory=dict)
    window_mapping: dict[str, str] = Field(default_factory=dict)
    event_timestamps: dict[str, int] = Field(default_factory=dict)
    # Chronological URL-change timeline rendered into the preamble. Defaults keep pre-existing Redis blobs loadable.
    navigation: list[NavigationEntry] = Field(default_factory=list)
    navigation_dropped: int = Field(default=0, ge=0)
    # True when the session hit the fetch row cap, so the events tool can't see the whole session.
    events_truncated: bool = False
    # Customer product context rendered into the preamble; empty for teams without core memory / descriptions.
    product_context: str = ""
    # Session-scoped custom-event descriptions, ordered by in-session frequency.
    event_descriptions: dict[str, str] = Field(default_factory=dict)
    metadata: SessionMetadata
    # Carried for signal emission, not the prompt — kept off `SessionMetadata` so it never reaches the LLM.
    distinct_id: str | None = None


class EnsureSessionAssetInputs(BaseModel, frozen=True):
    team_id: int
    session_id: str


class EnsureSessionAssetOutput(BaseModel, frozen=True):
    asset_id: int


class UploadVideoToGeminiInputs(BaseModel, frozen=True):
    asset_id: int


class UploadedVideo(BaseModel, frozen=True):
    file_uri: str
    mime_type: str
    gemini_file_name: str  # opaque ID for `files.delete`


class CallScannerProviderInputs(BaseModel, frozen=True):
    team_id: int
    observation_id: UUID  # locates the ScannerLlmInputs blob in Redis AND the scanner_snapshot on the row
    file_uri: str
    mime_type: str
    # When set, replaces the observation row's snapshot (evaluations re-run rated sessions with the suggested prompt).
    snapshot_override: ScannerSnapshot | None = None


class ScannerCallOutput(BaseModel, frozen=True):
    """Result of one `call_scanner_provider` invocation."""

    model_output: AnyScannerOutput
    # Extracted from the LLM response before `finalize` so per-type output mapping can't drop them.
    signals: list[SignalFinding] = Field(default_factory=list)


class CleanupGeminiFileInputs(BaseModel, frozen=True):
    gemini_file_name: str


class EmbedObservationInputs(BaseModel, frozen=True):
    """Input to the side-effect activity that emits embedding requests for an observation's reasoning/summary."""

    team_id: int
    session_id: str
    observation_id: UUID
    scanner_id: UUID
    model_output: AnyScannerOutput


class EmitClassifierTagsInputs(BaseModel, frozen=True):
    """Input to the classifier-side-effect activity that writes ai_tags_fixed/freeform via Kafka."""

    team_id: int
    session_id: str
    observation_id: UUID
    classifier_output: ClassifierOutput


class EmitObservationSignalInputs(BaseModel, frozen=True):
    """Input to the side-effect activity that emits the side-mission findings as PostHog Signals."""

    team_id: int
    observation_id: UUID
    exported_asset_id: int
    signals: list[SignalFinding]


class MarkObservationSucceededInputs(BaseModel, frozen=True):
    observation_id: UUID
    scanner_result: ScannerResult
    scanner_type: ScannerType


class EmitObservationEventInputs(BaseModel, frozen=True):
    """Payload for the `$recording_observed` capture."""

    observation_id: UUID
    model_output: AnyScannerOutput
