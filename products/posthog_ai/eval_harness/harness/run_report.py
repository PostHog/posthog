from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScoreReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    mean: float | None
    scored_trials: int


class ExperimentReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cases: dict[str, int]
    planned_trials: int
    completed_trials: int
    errors: int
    timeouts: int
    scores: dict[str, ScoreReport]
    log_dir: str


class RunReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal[1] = 1
    runtime: str
    model: str
    reasoning_effort: str | None
    provider: str
    trials: int
    suite_ids: list[str]
    suite_kinds: list[str]
    exit_code: int
    duration_seconds: float
    revision: str | None = None
    worktree_dirty: bool | None = None
    skills_sha256: str | None = None
    skills_manifest_path: str | None = None
    skills_source_sha256: str | None = None
    skills_archive_path: str | None = None
    experiments: dict[str, ExperimentReport] = Field(default_factory=dict)
