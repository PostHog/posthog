from __future__ import annotations

import json
import hashlib
from pathlib import Path, PurePosixPath
from typing import Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from products.posthog_ai.eval_harness.environment.table import ParquetTable


class EnvironmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class EnvironmentFile(EnvironmentModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def resolve(self, directory: Path) -> Path:
        relative = PurePosixPath(self.path)
        if relative.is_absolute() or ".." in relative.parts or "\\" in self.path:
            raise ValueError("Environment files must stay inside the bundle directory.")
        path = (directory / self.path).resolve(strict=True)
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError("Environment files must stay inside the bundle directory.")
        with path.open("rb") as content:
            digest = hashlib.file_digest(content, "sha256").hexdigest()
        if digest != self.sha256:
            raise ValueError(f"Environment checksum does not match: {self.path}")
        return path


class EnvironmentEvent(EnvironmentModel):
    uuid: UUID
    timestamp: AwareDatetime
    event: str = Field(min_length=1)
    distinct_id: str
    person_id: UUID | None = None
    properties: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: AwareDatetime

    @field_validator("properties", mode="before")
    @classmethod
    def decode_properties(cls, value: object) -> object:
        return json.loads(value) if isinstance(value, str) else value


class EnvironmentRow(EnvironmentModel):
    id: UUID
    team_id: int | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime | None = None


class EnvironmentMetric(EnvironmentRow):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$", max_length=128)
    display_name: str = Field(default="", max_length=255)
    description: str
    unit: str = Field(default="", max_length=64)
    owner_id: int | None = None
    definition: dict[str, JsonValue] | None = None
    referenced_table_names: list[str] = Field(default_factory=list)
    status: Literal["proposed", "approved"]
    approved_by_id: int | None = None
    approved_at: AwareDatetime | None = None
    source_insight_short_id: None = None
    source_insight_query_hash: None = None
    last_run_at: AwareDatetime | None = None
    created_source: Literal["user", "ai_generated"] = "user"
    ai_model: str = Field(default="", max_length=128)
    confidence: float | None = Field(default=None, ge=0, le=1)
    reasoning: str = ""
    created_by_id: int | None = None
    deleted: bool | None = False
    deleted_at: AwareDatetime | None = None


class EnvironmentTextPolicy(EnvironmentModel):
    time_strings: list[str] = Field(default_factory=list)
    string_replacements: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if "" in self.string_replacements:
            raise ValueError("String replacement keys cannot be empty.")
        if len(self.time_strings) != len(set(self.time_strings)):
            raise ValueError("Declared time strings must be unique.")
        return self


class EnvironmentManifest(EnvironmentTextPolicy):
    schema_version: Literal[1] = 1
    environment_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=128)
    source_cutoff: AwareDatetime
    checkpoint: AwareDatetime
    timezone: str = "UTC"
    events: list[EnvironmentFile] = Field(default_factory=list)
    metrics: EnvironmentFile | None = None
    event_count: int = Field(ge=0)
    metric_count: int = Field(ge=0)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as error:
            raise ValueError("The environment timezone must be an IANA timezone.") from error
        return value

    @model_validator(mode="after")
    def validate_checkpoint(self) -> Self:
        if self.checkpoint != self.source_cutoff:
            raise ValueError("Environment v1 requires its checkpoint to equal the source cutoff.")
        references = [*self.events, *([self.metrics] if self.metrics else [])]
        if len({file.path for file in references}) != len(references):
            raise ValueError("Environment data file paths must be unique.")
        return self


EVENT_TABLE = ParquetTable(EnvironmentEvent, json_fields={"properties"})
METRIC_TABLE = ParquetTable(EnvironmentMetric, json_fields={"definition", "referenced_table_names"})
