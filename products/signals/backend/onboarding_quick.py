"""Quick setup applied by the server, so an agent can activate Self-driving without the setup page.

The plan mirrors the browser's quick setup (`activateQuickSetup` in `inboxSetupLogic.ts` and
`quickInboxSetupDraft`), so both paths leave the same configuration. Change both together.
"""

from __future__ import annotations

import json
import hashlib
from collections.abc import Sequence
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from django.db import transaction

from requests import RequestException
from rest_framework import status
from rest_framework.exceptions import APIException

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.integrations import IntegrationManager
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.error_tracking.backend.facade.api import issue_exists
from products.event_definitions.backend.facade.api import recently_seen_event_names
from products.replay_vision.backend.facade.api import (
    OnboardingScanner,
    can_configure_onboarding_scanners,
    enable_onboarding_scanner_signals,
    enabled_onboarding_scanners,
    lock_onboarding_scanners,
)
from products.signals.backend.github_optional import GITHUB_OPTIONAL_ACTIVATION, ResearchAccessPolicy
from products.signals.backend.models import SignalScoutConfig, SignalSourceConfig, SignalTeamConfig
from products.signals.backend.onboarding_analytics import InboxOnboardingAnalytics
from products.signals.backend.scout_harness.config_registry import _resolve_seed_posture, enabled_scout_count
from products.signals.backend.scout_harness.lazy_seed import (
    canonical_deprecation_for,
    canonical_display_name_for,
    canonical_skill_names,
    scout_skill_row_origin,
)
from products.signals.backend.scout_harness.team_limits import (
    max_enabled_scouts_for_team,
    resolve_sync_seed_inputs,
    setup_default_skills_for_team,
    withheld_skills_for_team,
)
from products.signals.backend.trial.billing import trial_billing_status
from products.signals.backend.trial.limits import MAX_TRIAL_GRANTS_PER_ORGANIZATION
from products.signals.backend.trial.policy import TrialPolicy
from products.signals.backend.trial.service import TrialService
from products.skills.backend.models.skills import LLMSkill

if TYPE_CHECKING:
    from products.signals.backend.facade.onboarding import InboxOnboarding

GENERAL_SCOUT = "signals-scout-general"
ACTIVATION_METHOD = "mcp_tool"
IMPLEMENTATION_PRIORITY = "P1"
DEFAULT_SCOUT_INTERVAL_MINUTES = 1440
MAX_SCANNERS = 100
MAX_LISTED_REPOSITORIES = 100
TRIAL_SCOUT_LIMIT = 3
FINGERPRINT_VERSION = "v1"

PRODUCT_USAGE_EVENTS = ("$exception", "$ai_generation", "$ai_trace", "$pageview", "$autocapture")
# Product order and signal types follow `ONBOARDING_ROSTER_AGENTS` and `SOURCE_TYPES` in the browser's `inboxSetup.ts`.
ONBOARDING_SOURCE_PRODUCTS = (
    "error_tracking",
    "conversations",
    "replay_vision",
    "llm_analytics",
    "analytics",
    "health_checks",
)
ONBOARDING_SOURCE_TYPES: dict[str, tuple[str, ...]] = {
    "error_tracking": ("issue_created", "issue_reopened", "issue_spiking"),
    "conversations": ("ticket",),
    "llm_analytics": ("evaluation_report",),
    "analytics": ("anomaly_investigation",),
    "health_checks": ("health_issue",),
}
GENERAL_SCOUT_COPY = (
    "General scout",
    "Explore available project data, connect patterns across products, and investigate what needs attention.",
)
OTHER_SCOUT_WHY_HERE = "Watch this project on a schedule and report what needs your attention."

QuickActivationState = Literal["not_started", "in_progress", "completed"]
QuickActivationPricingKind = Literal["free_trial", "trial_claimed", "paid_plan", "existing_plan"]


class QuickActivationRejected(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "activation_rejected"
    default_detail = "Self-driving could not be activated from this plan."

    def __init__(self, detail: str, code: str) -> None:
        super().__init__(detail=detail, code=code)


@frozen
class QuickActivationBlocker:
    code: str
    message: str


@frozen
class QuickActivationSource:
    source_product: str
    source_type: str
    enabled_now: bool | None


@frozen
class QuickActivationScout:
    skill_name: str
    title: str
    run_interval_minutes: int
    run_cron_schedule: str | None
    enabled_now: bool
    config_id: UUID | None


@frozen
class QuickActivationGitHub:
    connected: bool
    integration_ids: tuple[int, ...]
    repositories: tuple[str, ...]
    more_repositories: bool


@frozen
class QuickActivationPricing:
    kind: QuickActivationPricingKind
    summary: str
    report_limit: int | None = None
    allowance_microusd: int | None = None
    blocker: QuickActivationBlocker | None = None


@frozen
class QuickActivationSelection:
    sources: tuple[QuickActivationSource, ...]
    scout_source_enabled_now: bool | None
    scanners: tuple[OnboardingScanner, ...]
    scouts: tuple[QuickActivationScout, ...]
    blockers: tuple[QuickActivationBlocker, ...]


@frozen
class QuickActivationPlan:
    state: QuickActivationState
    github: QuickActivationGitHub
    pricing: QuickActivationPricing
    github_optional: bool
    automatic_implementation: bool
    sources: tuple[QuickActivationSource, ...]
    scanner_ids: tuple[UUID, ...]
    scouts: tuple[QuickActivationScout, ...]
    blockers: tuple[QuickActivationBlocker, ...]
    fingerprint: str
    implementation_priority: str = IMPLEMENTATION_PRIORITY

    @property
    def can_activate(self) -> bool:
        return not self.blockers

    def draft(self) -> dict[str, Any]:
        """The draft the browser's quick setup sends to `onboarding/complete/` for the same project."""
        return {
            "onboarding_origin": "agent",
            **({"activation_mode": GITHUB_OPTIONAL_ACTIVATION} if self.github_optional else {}),
            "step": "github",
            "setup_mode": "quick",
            "sources": [
                {"source_product": source.source_product, "source_type": source.source_type, "enabled": True}
                for source in self.sources
            ],
            "scanner_ids": [str(scanner_id) for scanner_id in self.scanner_ids],
            "suggestions": [_suggestion(scout) for scout in self.scouts],
            "activation_scouts": [scout.skill_name for scout in self.scouts if not scout.enabled_now],
            "automatic_implementation": self.automatic_implementation,
            "implementation_priority": self.implementation_priority,
        }


def _suggestion(scout: QuickActivationScout) -> dict[str, Any]:
    return {
        "id": f"builtin:{scout.config_id or scout.skill_name}",
        "kind": "canonical",
        "skill_name": scout.skill_name,
        "title": scout.title,
        "why_here": GENERAL_SCOUT_COPY[1] if scout.skill_name == GENERAL_SCOUT else OTHER_SCOUT_WHY_HERE,
        "description": "",
        "draft_body": "",
        "proposed_config": {
            "run_interval_minutes": scout.run_interval_minutes,
            "run_cron_schedule": scout.run_cron_schedule,
            "emit": True,
        },
        "gap": True,
        "confidence": "medium",
    }


def _has_scopes(scopes: Sequence[str] | None, required: set[str]) -> bool:
    if scopes is None or "*" in scopes:
        return True
    held = set(scopes)
    held.update(f"{scope.removesuffix(':write')}:read" for scope in scopes if scope.endswith(":write"))
    return required.issubset(held)


def _onboarding_state(team: Team) -> QuickActivationState:
    config = SignalTeamConfig.objects.filter(team_id=team.id).first()
    onboarding = (config.onboarding or {}) if config else {}
    if onboarding.get("completed_at"):
        return "completed"
    return "in_progress" if onboarding.get("draft") else "not_started"


def _github_access(team: Team, *, list_repositories: bool) -> QuickActivationGitHub:
    integrations = sorted(IntegrationManager.github.oauth.list(team.id), key=lambda row: row.id)
    repositories: list[str] = []
    more_repositories = False
    if list_repositories:
        for integration in integrations:
            github = GitHubIntegration(integration, source="signals_onboarding", priority=Priority.NORMAL)
            try:
                page, has_more = github.list_repositories(per_page=MAX_LISTED_REPOSITORIES)
            except (GitHubIntegrationError, GitHubRateLimitError, EgressBudgetExhausted, RequestException):
                # The listing is shown to the person. Activation checks repository access again before it saves.
                more_repositories = True
                continue
            repositories.extend(repo["full_name"] for repo in page)
            more_repositories = more_repositories or has_more
    return QuickActivationGitHub(
        connected=bool(integrations),
        integration_ids=tuple(integration.id for integration in integrations),
        repositories=tuple(repositories[:MAX_LISTED_REPOSITORIES]),
        more_repositories=more_repositories or len(repositories) > MAX_LISTED_REPOSITORIES,
    )


def _usd(microusd: int) -> str:
    return f"${microusd / 1_000_000:,.2f}"


def _pricing(team: Team) -> QuickActivationPricing:
    """The terms `TrialService.enroll_on_activation` applies when quick setup turns on its first source."""
    policy = TrialPolicy(team)
    decision = policy.flag_decision()
    if decision.enabled is not True:
        return QuickActivationPricing(
            kind="existing_plan",
            summary="Usage is billed under your organization's current Self-driving plan and limits.",
        )
    if not decision.confirmed:
        return QuickActivationPricing(
            kind="existing_plan",
            summary="Self-driving pricing for this organization could not be checked.",
            blocker=QuickActivationBlocker(
                code="pricing_unavailable",
                message="Self-driving pricing could not be checked. Try again in a few minutes.",
            ),
        )
    grant = policy.grant()
    if grant is not None:
        return QuickActivationPricing(
            kind="trial_claimed",
            summary=(
                "This project already has a free trial. After it ends, usage is billed to your organization's "
                "Self-driving plan, up to its usage limit."
            ),
            report_limit=grant.report_limit,
            allowance_microusd=grant.allowance_microusd,
        )
    billing = trial_billing_status(team)
    if policy.organization_grants_claimed() >= MAX_TRIAL_GRANTS_PER_ORGANIZATION:
        if billing.paid_authorized:
            return QuickActivationPricing(
                kind="paid_plan",
                summary=(
                    "Your organization already used its free trial, so usage is billed to its Self-driving plan, "
                    "up to its usage limit."
                ),
            )
        return QuickActivationPricing(
            kind="paid_plan",
            summary="Your organization already used its free trial.",
            blocker=QuickActivationBlocker(
                code="trial_already_claimed",
                message="Your organization already used its free trial. Turn on paid Self-driving in billing first.",
            ),
        )
    limits = billing.limits
    terms = QuickActivationPricing(
        kind="free_trial",
        summary=(
            f"Starts a free trial: up to {limits.report_limit} reports or {_usd(limits.allowance_microusd)} of usage, "
            f"whichever comes first, with up to {TRIAL_SCOUT_LIMIT} scouts. After the trial, usage is billed to your "
            "organization's Self-driving plan, up to its usage limit."
        ),
        report_limit=limits.report_limit,
        allowance_microusd=limits.allowance_microusd,
    )
    if not billing.ready:
        return QuickActivationPricing(
            kind=terms.kind,
            summary=terms.summary,
            report_limit=terms.report_limit,
            allowance_microusd=terms.allowance_microusd,
            blocker=QuickActivationBlocker(
                code="billing_not_ready",
                message="Billing isn't ready for a Self-driving trial yet. Check your billing settings.",
            ),
        )
    return terms


def _recent_events(team: Team) -> set[str]:
    return recently_seen_event_names(team, PRODUCT_USAGE_EVENTS)


def _source_available(team: Team, product: str, events: set[str], has_scanners: bool) -> bool:
    if product == "error_tracking":
        return "$exception" in events or issue_exists(team.id)
    if product == "conversations":
        return bool(team.conversations_enabled)
    if product == "replay_vision":
        return has_scanners
    if product == "llm_analytics":
        return bool(events & {"$ai_generation", "$ai_trace"})
    if product == "analytics":
        return bool(events & {"$pageview", "$autocapture"})
    return bool(team.ingested_event)


def _sources(team: Team, has_scanners: bool, *, lock: bool) -> tuple[QuickActivationSource, ...]:
    rows = SignalSourceConfig.objects.filter(team_id=team.id, source_product__in=ONBOARDING_SOURCE_PRODUCTS)
    if lock:
        rows = rows.select_for_update().order_by("id")
    stored = {(row.source_product, row.source_type): row.enabled for row in rows}
    events = _recent_events(team)
    sources: list[QuickActivationSource] = []
    for product in ONBOARDING_SOURCE_PRODUCTS:
        if not _source_available(team, product, events, has_scanners):
            continue
        # Replay Vision has no fixed signal type, so the browser offers only the rows the project already has.
        types = ONBOARDING_SOURCE_TYPES.get(product) or tuple(
            sorted(source_type for source_product, source_type in stored if source_product == product)
        )
        sources.extend(
            QuickActivationSource(
                source_product=product, source_type=source_type, enabled_now=stored.get((product, source_type))
            )
            for source_type in types
        )
    return tuple(sources)


def _scout_source_enabled_now(canonical_team: Team, *, lock: bool) -> bool | None:
    rows = SignalSourceConfig.objects.filter(
        team_id=canonical_team.id,
        source_product=SignalSourceConfig.SourceProduct.SIGNALS_SCOUT,
        source_type=SignalSourceConfig.SourceType.CROSS_SOURCE_ISSUE,
    )
    if lock:
        rows = rows.select_for_update()
    row = rows.first()
    return row.enabled if row else None


def _scouts(
    canonical_team: Team, *, lock: bool
) -> tuple[tuple[QuickActivationScout, ...], list[QuickActivationBlocker]]:
    names = setup_default_skills_for_team(canonical_team.id)
    configs_query = SignalScoutConfig.objects.for_team(canonical_team.id).filter(skill_name__in=names)
    if lock:
        configs_query = configs_query.select_for_update().order_by("id")
    configs = {config.skill_name: config for config in configs_query}
    skills = {
        skill.name: skill
        for skill in LLMSkill.objects.filter(
            team_id=canonical_team.id, name__in=names, is_latest=True, deleted=False
        ).prefetch_related("files")
    }
    withheld = withheld_skills_for_team(canonical_team.id)
    layers, _ = resolve_sync_seed_inputs(canonical_team.id)
    enabled_skills, enabled_interval = _resolve_seed_posture(layers)
    # Matches the interval `register_missing_configs` gives a canonical scout, which the fleet sync creates before activation.
    seed_interval = (
        enabled_interval
        if enabled_skills is not None and enabled_interval is not None
        else DEFAULT_SCOUT_INTERVAL_MINUTES
    )
    scouts: list[QuickActivationScout] = []
    blockers: list[QuickActivationBlocker] = []
    for name in names:
        config = configs.get(name)
        skill = skills.get(name)
        # A seeded scout that the team edited is the team's own scout, so quick setup must not turn it on as canonical.
        usable = (
            name in canonical_skill_names()
            and name not in withheld
            and canonical_deprecation_for(name) is None
            and (skill is None or scout_skill_row_origin(skill) == "canonical")
            and (config is None or not config.lifecycle_locked)
        )
        if not usable:
            if name == GENERAL_SCOUT:
                blockers.append(
                    QuickActivationBlocker(
                        code="general_scout_unavailable",
                        message="The general scout isn't available for quick setup in this project.",
                    )
                )
            continue
        scouts.append(
            QuickActivationScout(
                skill_name=name,
                title=GENERAL_SCOUT_COPY[0]
                if name == GENERAL_SCOUT
                else ((config.display_name if config else "") or canonical_display_name_for(name) or name),
                run_interval_minutes=(config.run_interval_minutes or DEFAULT_SCOUT_INTERVAL_MINUTES)
                if config
                else seed_interval,
                run_cron_schedule=config.run_cron_schedule if config else None,
                enabled_now=bool(config and config.enabled),
                config_id=config.id if config else None,
            )
        )
    new_enables = sum(not scout.enabled_now for scout in scouts)
    if new_enables and enabled_scout_count(canonical_team.id) + new_enables > max_enabled_scouts_for_team(
        canonical_team.id
    ):
        blockers.append(
            QuickActivationBlocker(
                code="scout_limit",
                message="This project has reached its limit of enabled scouts. Turn one off before activating.",
            )
        )
    return tuple(scouts), blockers


def _selection(team: Team, user: User, *, lock: bool) -> QuickActivationSelection:
    canonical_team = team.parent_team or team
    scanners = tuple(enabled_onboarding_scanners(team, user, limit=MAX_SCANNERS + 1))
    blockers: list[QuickActivationBlocker] = []
    if len(scanners) > MAX_SCANNERS:
        blockers.append(
            QuickActivationBlocker(
                code="too_many_scanners",
                message="This project has more Replay Vision scanners than quick setup can include.",
            )
        )
    if lock and scanners:
        current = lock_onboarding_scanners(team, (scanner.id for scanner in scanners))
        scanners = tuple(
            OnboardingScanner(id=scanner.id, emits_signals=current[scanner.id], can_edit=scanner.can_edit)
            for scanner in scanners
            if scanner.id in current
        )
    scouts, scout_blockers = _scouts(canonical_team, lock=lock)
    return QuickActivationSelection(
        sources=_sources(team, bool(scanners), lock=lock),
        scout_source_enabled_now=_scout_source_enabled_now(canonical_team, lock=lock),
        scanners=scanners,
        scouts=scouts,
        blockers=(*blockers, *scout_blockers),
    )


def _fingerprint(
    team: Team,
    github: QuickActivationGitHub,
    pricing: QuickActivationPricing,
    github_optional: bool,
    automatic_implementation: bool,
    selection: QuickActivationSelection,
) -> str:
    # Covers every stored value the activation reads or changes, so an edit by anyone after the preview changes it.
    # Repository names are left out because the GitHub listing can fail on one call and pass on the next.
    payload = {
        "project": team.id,
        "scout_project": team.parent_team_id or team.id,
        "github": list(github.integration_ids),
        "pricing": [pricing.kind, pricing.report_limit, pricing.allowance_microusd],
        "github_optional": github_optional,
        "automatic_implementation": automatic_implementation,
        "implementation_priority": IMPLEMENTATION_PRIORITY,
        "sources": [[s.source_product, s.source_type, s.enabled_now] for s in selection.sources],
        "scout_source": selection.scout_source_enabled_now,
        "scanners": sorted([str(scanner.id), scanner.emits_signals] for scanner in selection.scanners),
        "scouts": [
            [s.skill_name, s.run_interval_minutes, s.run_cron_schedule, s.enabled_now] for s in selection.scouts
        ],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"{FINGERPRINT_VERSION}:{digest[:32]}"


def _permission_blockers(
    onboarding: InboxOnboarding,
    scopes: Sequence[str] | None,
    github_optional: bool,
    automatic_implementation: bool,
    selection: QuickActivationSelection,
) -> list[QuickActivationBlocker]:
    team, user = onboarding.team, onboarding.user
    missing: list[str] = []
    if not _has_scopes(scopes, {"inbox:write"}):
        missing.append("Your PostHog connection can't change Self-driving settings.")
    try:
        onboarding.authorize_scouts(True)
    except APIException as error:
        missing.append(str(error.detail))
    if automatic_implementation and not _has_scopes(scopes, {"task:write"}):
        missing.append("Your PostHog connection can't turn on automatic pull requests.")
    if github_optional and team.parent_team is not None:
        if not UserAccessControl(user=user, team=team.parent_team).check_access_level_for_resource("task", "editor"):
            missing.append("Activating this pilot requires task editor access on the parent project.")
    switched = [scanner for scanner in selection.scanners if not scanner.emits_signals]
    if switched and (
        not _has_scopes(scopes, {"replay_scanner:write", "session_recording:read"})
        or not can_configure_onboarding_scanners(team, user)
        or any(not scanner.can_edit for scanner in switched)
    ):
        missing.append("You need permission to edit this project's Replay Vision scanners.")
    if not missing:
        return []
    return [QuickActivationBlocker(code="missing_permission", message=" ".join(missing))]


def build_quick_activation_plan(
    onboarding: InboxOnboarding, scopes: Sequence[str] | None, *, list_repositories: bool = True
) -> QuickActivationPlan:
    team, user = onboarding.team, onboarding.user
    state = _onboarding_state(team)
    github = _github_access(team, list_repositories=list_repositories)
    pricing = _pricing(team)
    github_optional = ResearchAccessPolicy.enabled(team.id)
    usage_based_pricing = InboxOnboardingAnalytics.pricing_flag_for_team(team, user)
    # The browser turns on automatic pull requests only under legacy pricing. An unknown flag value keeps them off.
    automatic_implementation = not github_optional and usage_based_pricing is False
    selection = _selection(team, user, lock=False)
    blockers: list[QuickActivationBlocker] = []
    if state == "completed":
        blockers.append(QuickActivationBlocker(code="setup_completed", message="Self-driving is already set up."))
    elif state == "in_progress":
        blockers.append(
            QuickActivationBlocker(
                code="setup_in_progress", message="Setup already started for this project. Finish it in PostHog."
            )
        )
    if not github.connected:
        blockers.append(
            QuickActivationBlocker(code="github_not_connected", message="Connect GitHub in PostHog to activate.")
        )
    elif list_repositories and not github.repositories and not github.more_repositories:
        blockers.append(
            QuickActivationBlocker(
                code="github_no_repositories",
                message="The GitHub connection can't read any repositories. Give it access to at least one.",
            )
        )
    if pricing.blocker is not None:
        blockers.append(pricing.blocker)
    blockers.extend(selection.blockers)
    blockers.extend(_permission_blockers(onboarding, scopes, github_optional, automatic_implementation, selection))
    return QuickActivationPlan(
        state=state,
        github=github,
        pricing=pricing,
        github_optional=github_optional,
        automatic_implementation=automatic_implementation,
        sources=selection.sources,
        scanner_ids=tuple(scanner.id for scanner in selection.scanners),
        scouts=selection.scouts,
        blockers=tuple(blockers),
        fingerprint=_fingerprint(team, github, pricing, github_optional, automatic_implementation, selection),
    )


def _reject_started(config: SignalTeamConfig) -> None:
    onboarding = config.onboarding or {}
    if onboarding.get("completed_at") or onboarding.get("draft"):
        raise QuickActivationRejected(
            "Setup already started for this project, so quick activation is unavailable. Finish it in PostHog.",
            code="setup_started",
        )


def _lock_team_configs(team: Team, canonical_team: Team) -> dict[int, SignalTeamConfig]:
    for owner in sorted({team.id: team, canonical_team.id: canonical_team}.values(), key=lambda item: item.id):
        get_or_create_team_extension(owner, SignalTeamConfig)
    return {
        config.team_id: config
        for config in SignalTeamConfig.objects.select_for_update()
        .filter(team_id__in={team.id, canonical_team.id})
        .order_by("team_id")
    }


def _enable_source(team_id: int, source_product: str, source_type: str, user: User) -> bool:
    config, created = SignalSourceConfig.objects.get_or_create(
        team_id=team_id,
        source_product=source_product,
        source_type=source_type,
        defaults={"enabled": True, "created_by": user},
    )
    if not created and not config.enabled:
        config.enabled = True
        config.save(update_fields=["enabled", "updated_at"])
    return created


def _enable_scout(canonical_team: Team, user: User, scout: QuickActivationScout) -> None:
    from products.signals.backend.scout_harness.serializers import (  # noqa: PLC0415 - keeps the scout serializer graph off the onboarding import path
        SignalScoutConfigUpdateSerializer,
    )

    config = SignalScoutConfig.objects.for_team(canonical_team.id).select_for_update().get(skill_name=scout.skill_name)
    update = SignalScoutConfigUpdateSerializer(
        config,
        data={
            "enabled": True,
            "emit": True,
            "run_interval_minutes": scout.run_interval_minutes,
            "run_cron_schedule": scout.run_cron_schedule,
        },
        partial=True,
        # The serializer reads the acting user from the request, as on the scout config create endpoint the browser calls.
        context={
            "request": SimpleNamespace(user=user),
            "team": canonical_team,
            "project_id": canonical_team.project_id,
        },
    )
    update.is_valid(raise_exception=True)
    claims = not config.enabled or (config.enabled_by_id is None and not config.lifecycle_locked)
    update.save(**({"enabled_by": user} if claims else {}))


def apply_quick_activation(onboarding: InboxOnboarding, scopes: Sequence[str] | None, plan_fingerprint: str) -> None:
    """Apply the quick setup plan the person approved, or refuse when anything in it changed."""
    from products.signals.backend.scout_harness.fleet_sync import (  # noqa: PLC0415 - keeps the fleet sync graph off the onboarding import path
        materialize_scout_fleet,
    )

    team, user = onboarding.team, onboarding.user
    canonical_team = team.parent_team or team
    onboarding.authorize_scouts(True)
    _reject_started(get_or_create_team_extension(team, SignalTeamConfig))
    # The browser runs the same onboarding sync before it builds its draft, so scout configs exist to enable.
    materialize_scout_fleet(canonical_team, surface="onboarding")
    plan = build_quick_activation_plan(onboarding, scopes, list_repositories=False)
    if not plan.github.connected:
        raise QuickActivationRejected(
            "GitHub isn't connected to this project. Connect it in PostHog to activate.", code="github_not_connected"
        )
    if plan.fingerprint != plan_fingerprint:
        raise QuickActivationRejected(
            "The activation plan changed after it was shown. Get the plan again and confirm it.", code="plan_changed"
        )
    if plan.blockers:
        raise QuickActivationRejected(plan.blockers[0].message, code=plan.blockers[0].code)

    draft = plan.draft()
    preparation = onboarding.prepare_completion(draft)
    with (
        TrialService(team).enroll_on_activation(
            user=user, enabled=True, api_scopes=list(scopes) if scopes is not None else None, parent_access_allowed=True
        ),
        transaction.atomic(),
    ):
        configs = _lock_team_configs(team, canonical_team)
        _reject_started(configs[team.id])
        selection = _selection(team, user, lock=True)
        locked_fingerprint = _fingerprint(
            team, plan.github, plan.pricing, plan.github_optional, plan.automatic_implementation, selection
        )
        if locked_fingerprint != plan_fingerprint or selection.blockers:
            raise QuickActivationRejected(
                "Self-driving settings changed during activation. Get the plan again and confirm it.",
                code="plan_changed",
            )
        for config in configs.values():
            config.autostart_enabled = False
            config.save(update_fields=["autostart_enabled", "updated_at"])
        backfill = False
        for source in plan.sources:
            created = _enable_source(team.id, source.source_product, source.source_type, user)
            backfill = backfill or (
                created
                and source.source_product == SignalSourceConfig.SourceProduct.ERROR_TRACKING
                and source.source_type == SignalSourceConfig.SourceType.ISSUE_CREATED
            )
        enable_onboarding_scanner_signals(team, user, plan.scanner_ids)
        _enable_source(
            canonical_team.id,
            SignalSourceConfig.SourceProduct.SIGNALS_SCOUT,
            SignalSourceConfig.SourceType.CROSS_SOURCE_ISSUE,
            user,
        )
        max_enabled = max_enabled_scouts_for_team(canonical_team.id)
        for scout in plan.scouts:
            if (
                not scout.enabled_now
                and enabled_scout_count(canonical_team.id, exclude_skill=scout.skill_name) >= max_enabled
            ):
                raise QuickActivationRejected(
                    "This project has reached its limit of enabled scouts. Turn one off before activating.",
                    code="scout_limit",
                )
            _enable_scout(canonical_team, user, scout)
        config = configs[team.id]
        config.refresh_from_db()
        config.onboarding = {
            **(config.onboarding or {}),
            "activation_method": ACTIVATION_METHOD,
            # A job, unlike the browser's fire-and-forget start, is retried and re-sent until Temporal accepts it.
            **({"jobs": {"error_tracking_backfill": "pending"}} if backfill else {}),
        }
        config.save(update_fields=["onboarding", "updated_at"])
        onboarding.complete_prepared(draft, preparation)
