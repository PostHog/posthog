"""The skills-store skills a task sandbox lists as local skills.

The sandbox agent reads ``TaskRun.state["store_skills"]`` when its session starts and writes one
pointer ``SKILL.md`` per entry into its skill roots, so ``/<name>`` works there the way a local
skill does. The skill body still crosses the PostHog MCP only when the skill is invoked. The
selection runs here, in the worker that builds the processing context, so the sandbox makes no
request of its own for it on the session boot path.
"""

from typing import Any

import structlog

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_value

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.skills.backend.marketplace.adapters import SANDBOX_SKILLS_FEATURE_FLAG, select_skill_stubs
from products.skills.backend.marketplace.packaging import DEFAULT_BUNDLE_SKILLS
from products.skills.backend.models.skills import LLMSkill

logger = structlog.get_logger(__name__)

# Run state is read and rewritten by several activities, so each entry carries only what the
# harness needs to list the skill. The store allows 4096 characters; the harness listing shows far less.
STORE_SKILL_DESCRIPTION_MAX_CHARS = 300


def resolve_store_skills(team: Team, user: User, *, distinct_id: str, run_id: str) -> list[dict[str, Any]] | None:
    """The ``store_skills`` entries for a run, ``[]`` when the store is off for ``user``.

    ``None`` means the flag service did not answer. The caller then leaves the key alone, so a
    sandbox that resumes with stubs from an earlier session keeps them instead of losing them to an
    outage. ``user`` is whoever the sandbox's PostHog credential belongs to, because that is the
    identity ``skill-get`` will run as.
    """
    flag_value = posthog_feature_flag_value(
        SANDBOX_SKILLS_FEATURE_FLAG,
        distinct_id,
        organization_id=team.organization_id,
        team_id=team.id,
    )
    if flag_value is None:
        logger.warning("store_skills_flag_unavailable", run_id=run_id, team_id=team.id)
        return None
    if not flag_value:
        return []

    readable_skills = UserAccessControl(user=user, team=team).filter_queryset_by_access_level(
        LLMSkill.objects.filter(team=team), resource="llm_skill"
    )
    selection = select_skill_stubs(team, user, readable_skills, limit=DEFAULT_BUNDLE_SKILLS)
    logger.info(
        "store_skills_resolved",
        run_id=run_id,
        team_id=team.id,
        included=len(selection.stubs),
        dropped=selection.dropped_count,
        skipped=selection.skipped_count,
    )
    return [
        {
            "name": stub.name,
            "description": " ".join(stub.description.split())[:STORE_SKILL_DESCRIPTION_MAX_CHARS],
            "version": stub.version,
        }
        for stub in selection.stubs
    ]
