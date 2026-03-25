from dataclasses import dataclass
from functools import cached_property
from typing import Any

from posthog.temporal.data_imports.signals.registry import (
    SignalEmitterOutput,
    SignalSourceTableConfig,
    get_signal_config,
)

from products.data_warehouse.backend.types import ExternalDataSourceType

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


@dataclass
class EvalSignalSpec:
    """Specification for a single synthetic signal."""

    source: ExternalDataSourceType
    title: str
    body: str

    def _to_record(self) -> dict[str, Any]:
        title_field, body_field = _RECORD_FIELD_MAP[self.source]
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
        schema_name = _SOURCE_SCHEMA_MAP[self.source]
        config = get_signal_config(self.source.value, schema_name)
        if config is None:
            raise ValueError(f"No signal config registered for {self.source.value}/{schema_name}")
        return config

    @cached_property
    def content(self) -> SignalEmitterOutput:
        record = self._to_record()
        content = self.config.emitter(0, record)
        if content is None:
            raise ValueError(f"Content empty for {self.source.value}")
        return content


@dataclass
class EvalGroupSpec:
    """Specification for a single synthetic group."""

    scenario: str
    signals: list[EvalSignalSpec]
    actionable: bool = True
    safe: bool = True
