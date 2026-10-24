from __future__ import annotations

import json
import hashlib
from collections import Counter
from pathlib import PurePosixPath
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from products.posthog_ai.eval_harness.environment.schema import EnvironmentModel, EnvironmentTextPolicy


class ScoutEnvironmentUser(EnvironmentModel):
    id: str = Field(min_length=1)
    uuid: UUID | None = None
    first_name: str
    last_name: str = ""
    email: str = ""
    is_operator: bool = False
    github_login: str | None = None


class ScoutEnvironmentSkill(EnvironmentModel):
    id: UUID
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    body: str
    version: int = Field(ge=1)
    origin: Literal["canonical", "custom"]
    category: str = "scout"
    allowed_tools: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)
    file_content_types: dict[str, str] = Field(default_factory=dict)
    owners: list[str] = Field(default_factory=list)
    created_by: str | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    license: str = ""
    compatibility: str = ""

    @model_validator(mode="after")
    def validate_files(self) -> Self:
        for path in self.files:
            parsed = PurePosixPath(path)
            if not path or parsed.is_absolute() or ".." in parsed.parts or "\\" in path:
                raise ValueError("Skill files must have safe relative paths.")
        if set(self.file_content_types) - self.files.keys():
            raise ValueError("Skill content types must refer to supplied files.")
        return self


class ScoutEnvironmentRecord(EnvironmentModel):
    id: UUID
    created_at: AwareDatetime
    updated_at: AwareDatetime | None = None
    fields: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        if {"id", "pk", "team", "team_id", "created_at", "updated_at"} & self.fields.keys():
            raise ValueError("Record identity, tenancy, and version timestamps are separate fields.")
        return self


class ScoutEnvironmentStartingState(EnvironmentModel):
    profile: ScoutEnvironmentRecord | None = None
    notes: list[ScoutEnvironmentRecord] = Field(default_factory=list)
    memory: list[ScoutEnvironmentRecord] = Field(default_factory=list)
    runs: list[ScoutEnvironmentRecord] = Field(default_factory=list)
    reports: list[ScoutEnvironmentRecord] = Field(default_factory=list)
    report_artefacts: list[ScoutEnvironmentRecord] = Field(default_factory=list)
    tasks: list[ScoutEnvironmentRecord] = Field(default_factory=list)
    task_runs: list[ScoutEnvironmentRecord] = Field(default_factory=list)
    pull_requests: list[ScoutEnvironmentRecord] = Field(default_factory=list)
    report_assignments: list[ScoutEnvironmentRecord] = Field(default_factory=list)
    report_tasks: list[ScoutEnvironmentRecord] = Field(default_factory=list)

    def records(self) -> list[ScoutEnvironmentRecord]:
        return [
            *([self.profile] if self.profile else []),
            *self.notes,
            *self.memory,
            *self.runs,
            *self.reports,
            *self.report_artefacts,
            *self.tasks,
            *self.task_runs,
            *self.pull_requests,
            *self.report_assignments,
            *self.report_tasks,
        ]


class ScoutEnvironmentOrganization(EnvironmentModel):
    name: str | None = Field(default=None, min_length=1)
    is_ai_data_processing_approved: bool = False
    is_ai_training_opted_in: bool = False


class ScoutPromptTransformation(EnvironmentModel):
    source: str = Field(min_length=1)
    replacement: str
    reason: str = Field(min_length=1)
    expected_occurrences: int = Field(default=1, ge=1)


class ScoutEnvironmentCase(EnvironmentTextPolicy):
    schema_version: Literal[1] = 1
    environment_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=128)
    source_cutoff: AwareDatetime
    checkpoint: AwareDatetime
    timezone: str = "UTC"
    project_name: str | None = Field(default=None, min_length=1)
    organization: ScoutEnvironmentOrganization = Field(default_factory=ScoutEnvironmentOrganization)
    skill: ScoutEnvironmentSkill
    companion_skills: list[ScoutEnvironmentSkill] = Field(default_factory=list)
    config: dict[str, JsonValue] = Field(default_factory=dict)
    steering: str = ""
    prompt_mode: Literal["recorded", "native"] = "recorded"
    recorded_prompt: str = ""
    prompt_transformations: list[ScoutPromptTransformation] = Field(default_factory=list)
    expected_harness_prompt_version: str | None = None
    users: list[ScoutEnvironmentUser] = Field(default_factory=list)
    state: ScoutEnvironmentStartingState = Field(default_factory=ScoutEnvironmentStartingState)

    @model_validator(mode="after")
    def validate_starting_state(self) -> Self:
        if self.prompt_mode == "native" and (self.recorded_prompt or self.prompt_transformations):
            raise ValueError(
                "Native scout environments must use the ordinary harness prompt without recorded overrides."
            )
        skills = [self.skill, *self.companion_skills]
        identities = [*(skill.id for skill in skills), *(row.id for row in self.state.records())]
        work_claim_reports = {
            row.id: row.fields.get("report_id")
            for row in self.state.report_artefacts
            if row.fields.get("type") == "work_claim"
        }
        shared_legacy_claims = {
            row.id
            for row in self.state.report_assignments
            if isinstance(row.fields.get("report_id"), str)
            and row.fields["report_id"] == work_claim_reports.get(row.id)
        }
        if any(
            count != (2 if identity in shared_legacy_claims else 1) for identity, count in Counter(identities).items()
        ):
            raise ValueError("Starting-state record IDs must be unique.")
        if len({skill.name for skill in skills}) != len(skills):
            raise ValueError("Starting-state skill names must be unique.")
        users = {user.id for user in self.users}
        if len(users) != len(self.users) or sum(user.is_operator for user in self.users) > 1:
            raise ValueError("Source users must be unique and have at most one operator.")
        referenced_users = {
            user_id
            for skill in skills
            for user_id in [*skill.owners, *([skill.created_by] if skill.created_by else [])]
        }
        if referenced_users - users:
            raise ValueError("Skill authors and owners must refer to supplied users.")
        for record in self.state.records():
            if record.created_at > self.checkpoint or (record.updated_at and record.updated_at > self.checkpoint):
                raise ValueError("Starting state cannot contain versions written after the checkpoint.")
        for timestamp in (timestamp for skill in skills for timestamp in (skill.created_at, skill.updated_at)):
            if timestamp and timestamp > self.checkpoint:
                raise ValueError("The skill version must exist at the checkpoint.")
        return self

    def fingerprint(self) -> str:
        content = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(content.encode()).hexdigest()


class ScoutEnvironmentSeed(EnvironmentModel):
    environment_id: str
    team_id: int
    user_id: int
    config_id: UUID
    skill_id: UUID
    identity_map: dict[str, str]
    time_delta_seconds: float
    steering: str
