from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, Field, field_validator

from products.signals.backend.custom_agent.schemas import CustomAgentAssignee
from products.signals.backend.report_generation.research import ActionabilityAssessment, PriorityAssessment

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class CustomAgentResolverProtocol(Protocol):
    def consume_finalization_context(self) -> str: ...

    def current_report_context(self) -> str: ...

    async def send(
        self,
        prompt: str,
        output_model: type[_ModelT],
        *,
        label: str | None = None,
        include_report_context: bool = True,
        validation_retries: int | None = None,
    ) -> _ModelT: ...

    def register_title(self, title: str, *, overwrite: bool = False) -> None: ...

    def register_description(self, description: str, *, overwrite: bool = False) -> None: ...

    def register_actionability(
        self,
        actionability: ActionabilityAssessment,
        *,
        explanation: str | None = None,
        already_addressed: bool = False,
        overwrite: bool = False,
    ) -> None: ...

    def register_priority(
        self,
        priority: PriorityAssessment,
        *,
        explanation: str | None = None,
        overwrite: bool = False,
    ) -> None: ...

    def register_assignees(
        self,
        assignees: Sequence[CustomAgentAssignee | str | dict[str, Any]],
        *,
        overwrite: bool = False,
    ) -> None: ...


class _TitleResolution(BaseModel):
    title: str = Field(
        description="A concise PR-style Code Inbox report title scoped to one concrete concern.",
        max_length=96,
    )

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty")
        return value.strip()


class _DescriptionResolution(BaseModel):
    description: str = Field(
        description=(
            "Final Code Inbox report summary/description. Include what happened, evidence/root cause, "
            "and a concrete resolution path when actionable."
        )
    )

    @field_validator("description")
    @classmethod
    def description_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description must not be empty")
        return value.strip()


class _AssigneesResolution(BaseModel):
    assignees: list[CustomAgentAssignee] = Field(
        default_factory=list,
        description="Suggested GitHub assignees/reviewers. Return [] when no clear owner is supported by evidence.",
    )


def _final_prompt(agent: CustomAgentResolverProtocol, body: str) -> str:
    return "\n\n".join(
        part
        for part in [
            agent.consume_finalization_context(),
            agent.current_report_context(),
            body.strip(),
        ]
        if part.strip()
    )


async def resolve_title(agent: CustomAgentResolverProtocol) -> None:
    result = await agent.send(
        _final_prompt(
            agent,
            """Create the final report title.

Rules:
- Scope it to one concrete product/code concern.
- Prefer PR-style phrasing.
- Keep it short enough for Code Inbox list views.
- Do not include priority, assignee, or repository metadata in the title.""",
        ),
        _TitleResolution,
        label="resolve_title",
    )
    agent.register_title(result.title)


async def resolve_description(agent: CustomAgentResolverProtocol) -> None:
    result = await agent.send(
        _final_prompt(
            agent,
            """Create the final Code Inbox report description.

Use this structure when it fits:
- One-sentence tl;dr explaining why this matters.
- **What's happening:** concrete evidence from the work you just did.
- **Root cause:** the best-supported technical explanation.
- **How to resolve:** a concrete next action, unless the report is not actionable.

Be specific. Do not invent evidence.""",
        ),
        _DescriptionResolution,
        label="resolve_description",
    )
    agent.register_description(result.description)


async def resolve_actionability(agent: CustomAgentResolverProtocol) -> None:
    result = await agent.send(
        _final_prompt(
            agent,
            """Assess the final report actionability.

Use one of:
- `immediately_actionable`: a developer can act now with enough context.
- `requires_human_input`: a developer/user must choose missing scope or provide information first.
- `not_actionable`: no code/product action should be taken from this report.

Ground the explanation in the investigation so far.""",
        ),
        ActionabilityAssessment,
        label="resolve_actionability",
    )
    agent.register_actionability(result)


async def resolve_priority(agent: CustomAgentResolverProtocol) -> None:
    result = await agent.send(
        _final_prompt(
            agent,
            """Assign a final priority for this actionable report.

Priority guide:
- P0: critical production breakage, data loss, security, or core flow broken.
- P1: significant user-facing impact or strong regression evidence.
- P2: clear improvement/fix with contained scope.
- P3: useful but lower urgency.
- P4: minor cleanup or speculative benefit.

Explain the impact/scope, not just the implementation size.""",
        ),
        PriorityAssessment,
        label="resolve_priority",
    )
    agent.register_priority(result)


async def resolve_assignees(agent: CustomAgentResolverProtocol) -> None:
    result = await agent.send(
        _final_prompt(
            agent,
            """Suggest GitHub assignees/reviewers for this report.

Rules:
- Use GitHub logins only.
- Prefer owners/authors supported by code paths, blame/commit evidence, or obvious domain ownership.
- Return an empty list when no clear assignee is supported.
- Do not include placeholder users.""",
        ),
        _AssigneesResolution,
        label="resolve_assignees",
    )
    agent.register_assignees(result.assignees)
