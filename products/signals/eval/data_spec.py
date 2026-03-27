from dataclasses import dataclass
from functools import cached_property
from typing import Any

from posthog.temporal.data_imports.signals.registry import (
    SignalEmitterOutput,
    SignalSourceTableConfig,
    get_signal_config,
)

from products.data_warehouse.backend.types import ExternalDataSourceType

# Sentinel for error tracking signals (not a real ExternalDataSourceType)
ERROR_TRACKING = "error_tracking"

# Maps ExternalDataSourceType to the schema name used in the signal registry
_SOURCE_SCHEMA_MAP: dict[ExternalDataSourceType, str] = {
    ExternalDataSourceType.ZENDESK: "tickets",
    ExternalDataSourceType.GITHUB: "issues",
    ExternalDataSourceType.LINEAR: "issues",
}

# Maps ExternalDataSourceType to (title_field, body_field) in the emitter's record format
_RECORD_FIELD_MAP: dict[ExternalDataSourceType, tuple[str, str]] = {
    ExternalDataSourceType.ZENDESK: ("subject", "description"),
    ExternalDataSourceType.GITHUB: ("title", "body"),
    ExternalDataSourceType.LINEAR: ("title", "description"),
}

# Defaults for extra fields that Linear's _build_extra
_LINEAR_EXTRA_DEFAULTS: dict[str, Any] = {
    "url": "",
    "identifier": "",
    "number": 0,
    "priority": 0,
    "priority_label": "",
    "created_at": "",
    "updated_at": "",
}

# Preamble text for error tracking signal descriptions, matching cymbal's format
_ERROR_TRACKING_PREAMBLES: dict[str, str] = {
    "issue_created": "New error tracking issue created - this particular exception was observed for the first time",
    "issue_reopened": "Previously resolved error tracking issue has reappeared",
    "issue_spiking": "This error tracking issue is experiencing a spike in occurrences",
}

_ERROR_TRACKING_WEIGHTS: dict[str, float] = {
    "issue_created": 0.4,
    "issue_reopened": 0.7,
    "issue_spiking": 0.7,
}


def _render_error_tracking_description(title: str, body: str, source_type: str) -> str:
    """Render an error tracking signal description matching cymbal's format from signals.rs."""
    preamble = _ERROR_TRACKING_PREAMBLES.get(source_type, "Error tracking issue")
    return f"{preamble}:\n{title}\n\n```\n{body}\n```"


def _noop_emitter(_team_id: int, _record: dict[str, Any]) -> SignalEmitterOutput | None:
    return None


@dataclass
class EvalSignalSpec:
    """Specification for a single synthetic signal."""

    source: ExternalDataSourceType | str  # str for ERROR_TRACKING
    title: str
    body: str
    source_type_override: str = "issue_created"  # only used for error_tracking

    def _to_record(self) -> dict[str, Any]:
        title_field, body_field = _RECORD_FIELD_MAP[self.source]  # type: ignore[index]
        record: dict[str, Any] = {
            "id": 1,
            title_field: self.title,
            body_field: self.body,
        }
        if self.source == ExternalDataSourceType.LINEAR:
            record.update(_LINEAR_EXTRA_DEFAULTS)
        return record

    @cached_property
    def config(self) -> SignalSourceTableConfig:
        if self.source == ERROR_TRACKING:
            return SignalSourceTableConfig(
                source_product="error_tracking",
                source_type=self.source_type_override,
                emitter=_noop_emitter,
                partition_field="",
                fields=(),
            )
        schema_name = _SOURCE_SCHEMA_MAP[self.source]  # type: ignore[index]
        config = get_signal_config(self.source.value, schema_name)  # type: ignore[union-attr]
        if config is None:
            raise ValueError(f"No signal config registered for {self.source.value}/{schema_name}")  # type: ignore[union-attr]
        return config

    @cached_property
    def content(self) -> SignalEmitterOutput:
        if self.source == ERROR_TRACKING:
            return SignalEmitterOutput(
                source_product="error_tracking",
                source_type=self.source_type_override,
                source_id="eval-0",
                description=_render_error_tracking_description(self.title, self.body, self.source_type_override),
                weight=_ERROR_TRACKING_WEIGHTS.get(self.source_type_override, 0.4),
                extra={},
            )
        record = self._to_record()
        content = self.config.emitter(0, record)
        if content is None:
            raise ValueError(f"Content empty for {self.source.value}")  # type: ignore[union-attr]
        return content


@dataclass
class EvalGroupSpec:
    """Specification for a single synthetic group."""

    scenario: str
    signals: list[EvalSignalSpec]
    actionable: bool = True
    safe: bool = True
