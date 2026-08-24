"""Open a new user's first agent session."""

from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction

import structlog
import posthoganalytics

from posthog.constants import AvailableFeature
from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.models.user import User

from products.signals.backend.facade.api import enable_onboarding_signal_sources, visible_report_count
from products.tasks.backend.facade.api import (
    create_and_run_task,
    desktop_users_in_team,
    find_general_channel_id,
    organization_has_context,
)
from products.tasks.backend.facade.domain_research import normalize_target, research_domain
from products.tasks.backend.facade.onboarding_brief import (
    OnboardingFacts,
    build_followup,
    build_opening_brief,
    prose_list,
)
from products.tasks.backend.facade.onboarding_canvas import TeachingCanvas, ensure_teaching_canvas
from products.tasks.backend.facade.onboarding_prompt import (
    BUNDLED_ONBOARDING_PROMPT,
    load_onboarding_prompt,
    missing_onboarding_prompt_placeholders,
    render_onboarding_prompt,
)
from products.tasks.backend.models import Task, TaskClientProvenance

from ee.billing.salesforce_enrichment.constants import PERSONAL_EMAIL_DOMAINS

logger = structlog.get_logger(__name__)

ONBOARDING_SESSION_TITLE = "Getting set up"
ONBOARDING_SESSION_PAID_MODEL = "claude-opus-4-8"
ONBOARDING_SESSION_FREE_MODEL = "@cf/zai-org/glm-5.2"
ONBOARDING_SESSION_EFFORT = "medium"
ONBOARDING_SESSION_SCOPES = ["task:read", "task:write", "canvas:read"]

SPACES_FLAGS = ("code-spaces-layout", "project-bluebird")

ONBOARDING_ORIGIN_KEY_PREFIX = "desktop_onboarding_session"


def _origin_key(user_id: int) -> str:
    return f"{ONBOARDING_ORIGIN_KEY_PREFIX}:{user_id}"


def _started_session_id(team_id: int, user_id: int) -> UUID | None:
    return (
        Task.objects.filter(
            team_id=team_id,
            origin_key=_origin_key(user_id),
            created_by_id=user_id,
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        .values_list("id", flat=True)
        .first()
    )


def company_domain_from(email: str) -> str | None:
    _, _, domain = email.strip().lower().partition("@")
    if not domain or domain in PERSONAL_EMAIL_DOMAINS:
        return None
    return normalize_target(domain)


def onboarding_session_model(team: Team) -> str:
    if team.organization.is_feature_available(AvailableFeature.POSTHOG_CODE_USAGE):
        return ONBOARDING_SESSION_PAID_MODEL
    return ONBOARDING_SESSION_FREE_MODEL


def gather_onboarding_facts(team: Team, user: User) -> tuple[OnboardingFacts, str]:
    sources = enable_onboarding_signal_sources(team.id, user.id)

    if organization_has_context(team.organization_id):
        return (
            OnboardingFacts(
                org_has_context=True,
                has_events=bool(team.ingested_event),
                signal_reports_waiting=visible_report_count(team.id),
                other_members=prose_list(desktop_users_in_team(team, user.id)),
                sources_enabled=sources.labels,
                sources_watching=sources.watches,
                sources_newly_enabled=sources.newly_enabled,
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
        sources_enabled=sources.labels,
        sources_watching=sources.watches,
        sources_newly_enabled=sources.newly_enabled,
    )
    homepage = research.markdown or "" if research and research.outcome == "scraped" else ""
    return facts, homepage


def _session_enabled(team: Team, user: User) -> bool:
    if settings.DEBUG:
        return True

    distinct_id = user.distinct_id
    if not distinct_id:
        return False
    organization_id = str(team.organization_id)
    try:
        return all(
            bool(
                posthoganalytics.feature_enabled(
                    flag,
                    distinct_id=distinct_id,
                    groups={"organization": organization_id},
                    group_properties={"organization": {"id": organization_id}},
                    only_evaluate_locally=False,
                    send_feature_flag_events=False,
                )
            )
            for flag in SPACES_FLAGS
        )
    except Exception:
        logger.warning("onboarding_session_flag_check_failed", team_id=team.id)
        return False


def _teaching_canvas(team_id: int, channel_id: UUID, user: User) -> TeachingCanvas | None:
    """Best-effort: a session without the tour beats no session."""
    try:
        return ensure_teaching_canvas(team_id, channel_id, user)
    except Exception:
        logger.warning("onboarding_teaching_canvas_failed", team_id=team_id, exc_info=True)
        return None


def start_onboarding_session(team: Team, user: User) -> UUID | None:
    """Create the session a new user lands in. ``None`` when no session was started."""
    if not _session_enabled(team, user):
        logger.info("onboarding_session_skipped", team_id=team.id, reason="flag_disabled")
        return None

    channel_id = find_general_channel_id(team.id)
    if channel_id is None:
        logger.info("onboarding_session_skipped", team_id=team.id, reason="no_general_channel")
        return None

    started = _started_session_id(team.id, user.id)
    if started is not None:
        logger.info("onboarding_session_skipped", team_id=team.id, reason="already_started")
        return started

    origin_key = _origin_key(user.id)

    teaching = _teaching_canvas(team.id, channel_id, user)
    facts, homepage = gather_onboarding_facts(team, user)
    prompt = load_onboarding_prompt()
    missing_placeholders = missing_onboarding_prompt_placeholders(prompt.prompt)
    prompt_template = prompt.prompt
    if missing_placeholders:
        logger.error(
            "onboarding_prompt_missing_placeholders",
            missing_placeholders=missing_placeholders,
            prompt_source=prompt.source,
            prompt_version=prompt.version,
            team_id=team.id,
        )
        posthoganalytics.capture(
            distinct_id=str(user.distinct_id),
            event="Onboarding prompt fallback used",
            properties={
                "reason": "missing_placeholders",
                "missing_placeholders": missing_placeholders,
                "prompt_source": prompt.source,
                "prompt_version": prompt.version,
            },
            groups=groups(team.organization, team),
        )
        prompt_template = BUNDLED_ONBOARDING_PROMPT
    description = render_onboarding_prompt(
        prompt_template,
        brief=build_opening_brief(facts),
        followup=build_followup(facts, teaching=teaching),
        homepage=homepage,
        channel_id=str(channel_id),
    )

    try:
        with transaction.atomic():
            created = create_and_run_task(
                team=team,
                title=ONBOARDING_SESSION_TITLE,
                description=description,
                origin_product=Task.OriginProduct.USER_CREATED,
                user_id=user.id,
                channel_id=channel_id,
                origin_key=origin_key,
                client_provenance=TaskClientProvenance.POSTHOG_DESKTOP,
                create_pr=False,
                mode="interactive",
                model=onboarding_session_model(team),
                reasoning_effort=ONBOARDING_SESSION_EFFORT,
                posthog_mcp_scopes=ONBOARDING_SESSION_SCOPES,
                initial_permission_mode="auto",
            )
    except IntegrityError:
        started = _started_session_id(team.id, user.id)
        if started is None:
            raise
        logger.info("onboarding_session_skipped", team_id=team.id, reason="already_started")
        return started
    logger.info(
        "onboarding_session_started",
        team_id=team.id,
        prompt_source=prompt.source,
        prompt_version=prompt.version,
        research_outcome=facts.research.outcome if facts.research else None,
        sources_enabled=facts.sources_enabled,
        sources_newly_enabled=facts.sources_newly_enabled,
    )
    return created.task_id
