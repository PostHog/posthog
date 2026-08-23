"""Open a new user's first agent session."""

from uuid import UUID

import structlog
import posthoganalytics

from posthog.models.team.team import Team
from posthog.models.user import User

from products.signals.backend.facade.api import visible_report_count
from products.tasks.backend.facade.api import (
    create_and_run_task,
    desktop_users_in_team,
    find_general_channel_id,
    organization_has_context,
)
from products.tasks.backend.facade.domain_research import normalize_target, research_domain
from products.tasks.backend.facade.onboarding_brief import OnboardingFacts, build_opening_brief
from products.tasks.backend.facade.onboarding_prompt import load_onboarding_prompt, render_onboarding_prompt
from products.tasks.backend.models import Task

from ee.billing.salesforce_enrichment.constants import PERSONAL_EMAIL_DOMAINS

logger = structlog.get_logger(__name__)

ONBOARDING_SESSION_TITLE = "Getting set up"

ONBOARDING_SESSION_MODEL = "claude-opus-4-8"

# The session lands in #general, so it is gated on the flag that decides whether spaces exist
# for this person at all. Nothing to gain from a second rollout dial.
SPACES_LAYOUT_FLAG = "code-spaces-layout"


def company_domain_from(email: str) -> str | None:
    _, _, domain = email.strip().lower().partition("@")
    if not domain or domain in PERSONAL_EMAIL_DOMAINS:
        return None
    return normalize_target(domain)


def _company_of(names: list[str]) -> str | None:
    if not names:
        return None
    if len(names) == 1:
        return names[0]
    if len(names) <= 3:
        return f"{', '.join(names[:-1])} and {names[-1]}"
    return f"{', '.join(names[:2])} and {len(names) - 2} others"


def gather_onboarding_facts(team: Team, user: User) -> tuple[OnboardingFacts, str]:
    """The facts behind the opening message, and the page text its summary is drawn from."""
    others = _company_of(desktop_users_in_team(team.id, user.id))

    if organization_has_context(team.organization_id):
        return (
            OnboardingFacts(
                org_has_context=True,
                signal_reports_waiting=visible_report_count(team.id),
                other_members=others,
            ),
            "",
        )

    domain = company_domain_from(user.email)
    research = research_domain(domain) if domain else None
    facts = OnboardingFacts(
        org_has_context=False,
        research=research,
        has_events=bool(team.ingested_event),
        signal_reports_waiting=visible_report_count(team.id),
        other_members=others,
    )
    homepage = research.markdown or "" if research and research.outcome == "scraped" else ""
    return facts, homepage


def _session_enabled(team: Team, user: User) -> bool:
    distinct_id = user.distinct_id
    if not distinct_id:
        return False
    organization_id = str(team.organization_id)
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SPACES_LAYOUT_FLAG,
                distinct_id=distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.warning("onboarding_session_flag_check_failed", team_id=team.id)
        return False


def start_onboarding_session(team: Team, user: User) -> UUID | None:
    """Create the session a new user lands in. ``None`` when no session was started."""
    if not _session_enabled(team, user):
        return None

    channel_id = find_general_channel_id(team.id)
    if channel_id is None:
        return None

    facts, homepage = gather_onboarding_facts(team, user)
    prompt = load_onboarding_prompt()
    description = render_onboarding_prompt(prompt.prompt, brief=build_opening_brief(facts), homepage=homepage)

    created = create_and_run_task(
        team=team,
        title=ONBOARDING_SESSION_TITLE,
        description=description,
        origin_product=Task.OriginProduct.USER_CREATED,
        user_id=user.id,
        channel_id=channel_id,
        create_pr=False,
        mode="interactive",
        model=ONBOARDING_SESSION_MODEL,
    )
    logger.info(
        "onboarding_session_started",
        team_id=team.id,
        prompt_source=prompt.source,
        prompt_version=prompt.version,
        research_outcome=facts.research.outcome if facts.research else None,
    )
    return created.task_id
