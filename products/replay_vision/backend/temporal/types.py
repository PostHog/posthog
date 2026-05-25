import datetime as dt
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, model_validator
from temporalio.exceptions import ApplicationError

from products.replay_vision.backend.models.replay_observation import ObservationTrigger
from products.replay_vision.backend.models.replay_scanner import ScannerModel, ScannerProvider, ScannerType
from products.replay_vision.backend.temporal.constants import MAX_SESSION_ID_LENGTH
from products.replay_vision.backend.temporal.scanners.classifier import ClassifierOutput
from products.replay_vision.backend.temporal.scanners.indexer import IndexerOutput
from products.replay_vision.backend.temporal.scanners.monitor import MonitorOutput
from products.replay_vision.backend.temporal.scanners.scorer import ScorerOutput
from products.replay_vision.backend.temporal.scanners.summarizer import SummarizerOutput

AnyScannerOutput = Annotated[
    ClassifierOutput | IndexerOutput | MonitorOutput | ScorerOutput | SummarizerOutput,
    Field(discriminator="scanner_type"),
]


class ScannerSnapshot(BaseModel, frozen=True):
    """Frozen view of a `ReplayScanner` at observation-create time, persisted into `ReplayObservation.scanner_snapshot`."""

    name: str
    scanner_type: ScannerType
    scanner_version: int = Field(ge=1)
    model: ScannerModel
    provider: ScannerProvider
    emits_signals: bool
    scanner_config: dict[str, Any]

    @classmethod
    def load_for(cls, observation_id: UUID, raw: dict[str, Any] | None) -> "ScannerSnapshot":
        """Validate a persisted `scanner_snapshot` blob, raising a non-retryable error tagged with the observation id."""
        try:
            return cls.model_validate(raw or {})
        except ValidationError as exc:
            raise ApplicationError(
                f"ReplayObservation {observation_id} has malformed scanner_snapshot: {exc}", non_retryable=True
            ) from exc


class EventCitation(BaseModel, frozen=True):
    """One entry in `event_id_mapping`: enough metadata for a UI to render a deep-link to the cited event."""

    uuid: str = Field(description="Real PostHog event UUID; use with `/api/.../events/{uuid}` to fetch the event.")
    timestamp_ms: int = Field(
        ge=0, description="Milliseconds since session start; use to seek the session replay player to the moment."
    )


class ScannerResult(BaseModel, frozen=True):
    """Result data of a completed observation, persisted into `ReplayObservation.scanner_result`."""

    model_output: AnyScannerOutput
    signals_count: int = Field(default=0, ge=0)
    event_id_mapping: dict[str, EventCitation] = Field(default_factory=dict)


class ApplyScannerInputs(BaseModel, frozen=True):
    """Input to ApplyScannerWorkflow."""

    scanner_id: UUID
    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_LENGTH)
    team_id: int
    triggered_by: ObservationTrigger
    triggered_by_user_id: int | None = None


class CreateObservationInputs(BaseModel, frozen=True):
    scanner_id: UUID
    team_id: int
    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_LENGTH)
    triggered_by: ObservationTrigger
    triggered_by_user_id: int | None
    workflow_id: str


class CreateObservationOutput(BaseModel, frozen=True):
    """`was_created=False` means the row already existed; the caller should no-op."""

    observation_id: UUID
    was_created: bool


class MarkObservationRunningInputs(BaseModel, frozen=True):
    observation_id: UUID


class MarkObservationFailedInputs(BaseModel, frozen=True):
    observation_id: UUID
    error_reason: str


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
    events_truncated: bool = False

    def as_prompt_dict(self) -> dict[str, Any]:
        """Drop unset (None) fields so the prompt isn't padded with `null`s."""
        return self.model_dump(mode="json", exclude_none=True)


class ScannerLlmInputs(BaseModel, frozen=True):
    """Per-session analytics events + recording metadata, stashed in Redis between activities."""

    session_id: str
    team_id: int
    events: EventTable
    # Reverse mappings: `url_1` -> actual URL, `window_1` -> actual window UUID.
    url_mapping: dict[str, str] = Field(default_factory=dict)
    window_mapping: dict[str, str] = Field(default_factory=dict)
    event_id_mapping: dict[str, EventCitation] = Field(default_factory=dict)
    metadata: SessionMetadata


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


class ScannerCallOutput(BaseModel, frozen=True):
    """Result of one `call_scanner_provider` invocation."""

    model_output: AnyScannerOutput
    # Short event_id (LLM-facing) -> citation metadata, propagated from `ScannerLlmInputs` for downstream resolution.
    event_id_mapping: dict[str, EventCitation] = Field(default_factory=dict)


class CleanupGeminiFileInputs(BaseModel, frozen=True):
    gemini_file_name: str


class EmbedIndexerObservationInputs(BaseModel, frozen=True):
    """Input to the indexer-side-effect activity that emits per-facet embedding requests."""

    team_id: int
    session_id: str
    observation_id: UUID
    indexer_output: IndexerOutput


class EmitClassifierTagsInputs(BaseModel, frozen=True):
    """Input to the classifier-side-effect activity that writes ai_tags_fixed/freeform via Kafka."""

    team_id: int
    session_id: str
    observation_id: UUID
    classifier_output: ClassifierOutput


class MarkObservationSucceededInputs(BaseModel, frozen=True):
    observation_id: UUID
    scanner_result: ScannerResult


class EmitObservationEventInputs(BaseModel, frozen=True):
    """Payload for the `$recording_observed` capture."""

    observation_id: UUID
    model_output: AnyScannerOutput
