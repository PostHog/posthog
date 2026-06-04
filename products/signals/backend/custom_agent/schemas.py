from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from posthog.schema import RelevantCommit

from products.signals.backend.report_generation.research import ActionabilityAssessment, PriorityAssessment

if TYPE_CHECKING:
    from products.signals.backend.custom_agent.base import CustomSignalAgent

_IDENTIFIER_PART_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class CustomAgentIdentifierError(ValueError):
    """Raised when a custom agent product/type/run identifier is not safe for routing."""


def validate_identifier_part(value: str, *, field_name: str) -> str:
    """Validate a product/type component used in workflow IDs and routing."""
    normalized = value.strip()
    if not normalized:
        raise CustomAgentIdentifierError(f"{field_name} must not be empty")
    if not _IDENTIFIER_PART_RE.fullmatch(normalized):
        raise CustomAgentIdentifierError(
            f"{field_name} must contain only lowercase letters, numbers, underscores, or hyphens, "
            "and must start with a lowercase letter or number"
        )
    return normalized


def validate_identifier(product: str, type_: str) -> tuple[str, str]:
    return (
        validate_identifier_part(product, field_name="product"),
        validate_identifier_part(type_, field_name="type"),
    )


def validate_run_id(value: str) -> str:
    return validate_identifier_part(value, field_name="id")


def validated_identifier(agent_class: type[CustomSignalAgent]) -> tuple[str, str]:
    """Call ``agent_class.identifier()`` and verify its shape + part syntax."""
    identifier = agent_class.identifier()
    if not isinstance(identifier, tuple) or len(identifier) != 2:
        raise CustomAgentIdentifierError("identifier() must return a (product, type) tuple")
    return validate_identifier(identifier[0], identifier[1])


class CustomAgentAssignee(BaseModel):
    github_login: str = Field(description="GitHub username/login to suggest as reviewer or assignee.")
    github_name: str | None = Field(default=None, description="Optional display name from GitHub.")
    relevant_commits: list[RelevantCommit] = Field(
        default_factory=list,
        description="Optional commit evidence explaining why this assignee is relevant.",
    )

    @field_validator("github_login")
    @classmethod
    def normalize_github_login(cls, value: str) -> str:
        normalized = value.strip().lower().lstrip("@")
        if not normalized:
            raise ValueError("github_login must not be empty")
        return normalized


@dataclass(frozen=True)
class CustomAgentRunHandle:
    workflow_id: str
    run_id: str
    started: bool
    """True if this call started the workflow; False if a workflow with the same id was already running."""


@dataclass
class CustomAgentWorkflowInput:
    team_id: int
    agent_path: str
    product: str
    type: str
    run_id: str
    initial_prompt: str
    repository: str | None
    model: str | None = None


@dataclass
class CustomAgentWorkflowOutput:
    report_ids: list[str]
    repository: str | None
    task_id: str | None


@dataclass(frozen=True)
class CustomAgentFinalReport:
    title: str
    description: str
    actionability: ActionabilityAssessment
    assignees: list[CustomAgentAssignee]
    priority: PriorityAssessment | None
