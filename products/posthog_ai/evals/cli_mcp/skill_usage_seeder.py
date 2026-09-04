"""Seeder hook that installs a project-scoped skill into a per-case team.

The skill-usage eval's ``project`` source arm needs a real ``project:`` skill the
agent can discover, load, and pull a reference file from. This seeder writes one
``LLMSkill`` (with a body that instructs applying an exclusion rule documented in a
reference file) and its ``LLMSkillFile`` reference onto the per-case team, so the
MCP ``learn`` command surfaces it under ``project:``.

Runs synchronously in a worker thread (``asyncio.to_thread``) from ``base.py:task()``
after the per-case team/user has been provisioned; the returned dict is merged into
the task output under ``seed`` for scorers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext

__all__ = [
    "PROJECT_SKILL_NAME",
    "PROJECT_SKILL_DESCRIPTION",
    "PROJECT_SKILL_REFERENCE_PATH",
    "PROJECT_SKILL_PLAN",
    "PROJECT_SKILL_EXCLUSION_FLOOR_USD",
    "PROJECT_SKILL_RULE_LABEL",
    "PROJECT_SKILL_BODY",
    "PROJECT_SKILL_REFERENCE_CONTENT",
    "PROJECT_SKILL_EXPECTED_ANSWER",
    "seed_project_skill",
]

PROJECT_SKILL_NAME = "hedgebox-revenue-policy"
PROJECT_SKILL_REFERENCE_PATH = "references/policy-details.md"
PROJECT_SKILL_PLAN = "business/enterprise"
PROJECT_SKILL_EXCLUSION_FLOOR_USD = 500
PROJECT_SKILL_RULE_LABEL = "REV-7"

PROJECT_SKILL_DESCRIPTION = (
    "How Hedgebox defines qualified enterprise revenue for finance reporting. Qualified enterprise "
    f"revenue counts only `paid_bill` events on the `{PROJECT_SKILL_PLAN}` plan, and rule "
    f"{PROJECT_SKILL_RULE_LABEL} must be applied to drop pilot-tier bills before the figure is reported "
    f"to finance. Read `{PROJECT_SKILL_REFERENCE_PATH}` for the exact exclusions before quoting a number."
)

PROJECT_SKILL_BODY = f"""# Hedgebox revenue policy

Use this skill whenever finance asks for **qualified enterprise revenue**.

## Definition

Qualified enterprise revenue is the SUM of the `paid_bill` event's `amount_usd`
property, filtered to bills on the `{PROJECT_SKILL_PLAN}` plan (the `plan` property
equals `'{PROJECT_SKILL_PLAN}'`). Bills on any other plan do not count.

## Before reporting

Before reporting the number to finance, apply the exclusions documented in
`{PROJECT_SKILL_REFERENCE_PATH}`. Quoting a total without applying those exclusions
is incorrect. Read that reference file and state which rules you applied.
"""

PROJECT_SKILL_REFERENCE_CONTENT = f"""# Policy details

## Rule {PROJECT_SKILL_RULE_LABEL}

Exclude any individual `paid_bill` whose `amount_usd` is below
${PROJECT_SKILL_EXCLUSION_FLOOR_USD} from qualified enterprise revenue. These are
pilot-tier billing charges and must not be counted toward the figure reported to
finance, even when they sit on the `{PROJECT_SKILL_PLAN}` plan.
"""

PROJECT_SKILL_EXPECTED_ANSWER = (
    "Revenue was computed from the `paid_bill` event's `amount_usd` filtered to the "
    f"`{PROJECT_SKILL_PLAN}` plan. Rule {PROJECT_SKILL_RULE_LABEL} was applied, excluding any individual "
    f"paid_bill under ${PROJECT_SKILL_EXCLUSION_FLOOR_USD} (pilot-tier billing) from qualified revenue. "
    "The answer reports a total USD figure."
)


def seed_project_skill(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Create the project-scoped revenue-policy skill and its reference file for the case team."""
    from products.skills.backend.models.skills import LLMSkill, LLMSkillFile, category_for_skill_name

    skill = LLMSkill.objects.create(
        team_id=context.team_id,
        name=PROJECT_SKILL_NAME,
        description=PROJECT_SKILL_DESCRIPTION,
        body=PROJECT_SKILL_BODY,
        category=category_for_skill_name(PROJECT_SKILL_NAME),
        created_by_id=context.user_id,
    )
    LLMSkillFile.objects.create(
        skill=skill,
        path=PROJECT_SKILL_REFERENCE_PATH,
        content=PROJECT_SKILL_REFERENCE_CONTENT,
        content_type="text/markdown",
    )
    return {
        "project_skill_id": str(skill.id),
        "project_skill_name": PROJECT_SKILL_NAME,
        "reference_path": PROJECT_SKILL_REFERENCE_PATH,
    }
