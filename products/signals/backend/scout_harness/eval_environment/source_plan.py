from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from products.posthog_ai.eval_harness.environment.schema import EnvironmentModel
from products.signals.backend.scout_harness.eval_environment.schema import ScoutEnvironmentUser


class SourcePropertyFilter(EnvironmentModel):
    name: str = Field(min_length=1)
    values: list[str | int | float | bool] = Field(min_length=1)


class SourceEventWindow(EnvironmentModel):
    start: AwareDatetime
    end: AwareDatetime
    events: list[str] = Field(min_length=1)
    properties: list[SourcePropertyFilter] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.start >= self.end or any(not name for name in self.events):
            raise ValueError("Event windows need a nonempty interval and explicit event names.")
        return self


class SourceSlicePlan(EnvironmentModel):
    schema_version: Literal[1] = 1
    environment_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=128)
    purpose: Literal["scout", "events_only"] = "scout"
    project_id: int = Field(gt=0)
    skill_name: str = Field(min_length=1, max_length=64)
    companion_skill_names: list[str] = Field(default_factory=list)
    draft_skill: Path | None = None
    draft_config: dict[str, JsonValue] = Field(default_factory=dict)
    profile_snapshot: Path | None = None
    event_windows: list[SourceEventWindow] = Field(default_factory=list)
    metric_names: list[str] = Field(default_factory=list)
    history_from: AwareDatetime
    report_ids: list[UUID] = Field(default_factory=list)
    memory_keys: list[str] | None = None
    dependencies: list[str] = Field(min_length=1)
    selection_reason: str = Field(min_length=1)
    steering: str = ""
    users: list[ScoutEnvironmentUser] = Field(default_factory=list)
    source_cutoff: AwareDatetime
    max_events: int = Field(default=100_000, ge=0)
    max_context_rows: int = Field(default=10_000, ge=1)
    page_size: int = Field(default=1000, ge=1, le=1000)
    time_strings: list[str] = Field(default_factory=list)
    text_time_policy_reviewed: bool = False
    string_replacements: dict[str, str] = Field(default_factory=dict)
    source_project_url: str | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.skill_name in self.companion_skill_names or len(set(self.companion_skill_names)) != len(
            self.companion_skill_names
        ):
            raise ValueError("Companion skills must be unique and different from the selected Scout.")
        supported = {"events", "data_catalog_metrics", "scout_context"}
        missing = sorted(set(self.dependencies) - supported)
        if missing:
            raise ValueError("Unsupported source dependencies require separate adapters: " + ", ".join(missing))
        if self.history_from >= self.source_cutoff:
            raise ValueError("History must begin before the export cutoff.")
        if any(window.end > self.source_cutoff for window in self.event_windows):
            raise ValueError("Event windows cannot end after the export cutoff.")
        if bool(self.event_windows) != ("events" in self.dependencies):
            raise ValueError("Declare events exactly when event windows are selected.")
        if bool(self.metric_names) != ("data_catalog_metrics" in self.dependencies):
            raise ValueError("Declare data_catalog_metrics exactly when metrics are selected.")
        if self.purpose == "scout" and "scout_context" not in self.dependencies:
            raise ValueError("A runnable Scout export requires scout_context.")
        if self.purpose == "events_only" and set(self.dependencies) != {"events"}:
            raise ValueError("An events-only export declares only events and does not create a runnable Scout bundle.")
        if len(set(self.metric_names)) != len(self.metric_names):
            raise ValueError("Metric names must be unique.")
        if self.draft_skill is None and self.draft_config:
            raise ValueError("Only a draft skill accepts draft configuration overrides.")
        return self

    def assert_current(self, now: datetime) -> None:
        if self.source_cutoff > now:
            raise ValueError("The source cutoff cannot be in the future.")
