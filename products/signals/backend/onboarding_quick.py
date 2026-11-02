from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from rest_framework.exceptions import APIException

from posthog.dataclasses import frozen
from posthog.models import EventDefinition
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.taxonomy.taxonomy import STALE_EVENT_DAYS

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.error_tracking.backend.facade.api import issue_exists
from products.replay_vision.backend.facade.onboarding import (
    enable_onboarding_scanner_signals,
    enabled_onboarding_scanners,
    has_enabled_onboarding_scanners,
)
from products.signals.backend.first_report_scout import first_report_state
from products.signals.backend.github_optional import ResearchAccessPolicy
from products.signals.backend.models import SignalScoutConfig, SignalSourceConfig, SignalTeamConfig
from products.signals.backend.onboarding_completion import InboxOnboardingReconciler
from products.signals.backend.onboarding_pricing import onboarding_usage_based_pricing
from products.signals.backend.scout_harness.config_registry import _resolve_seed_posture, enabled_scout_count
from products.signals.backend.scout_harness.lazy_seed import (
    canonical_deprecation_for,
    canonical_skill_names,
    registered_scout_skill_origin,
)
from products.signals.backend.scout_harness.run_gates import check_fleet_gates, check_spend_gates
from products.signals.backend.scout_harness.team_limits import (
    max_enabled_scouts_for_team,
    resolve_sync_seed_inputs,
    team_is_enrolled_after_onboarding,
)
from products.signals.backend.source_backfill import trigger_error_tracking_backfill

if TYPE_CHECKING:
    from rest_framework.request import Request

    from products.signals.backend.facade.onboarding import InboxOnboarding

GENERAL_SCOUT = "signals-scout-general"
ACTIVATION_ENTRYPOINT = "mcp_error_tracking"
ActivationMode = Literal["standard", "github_optional"]
ActivationState = Literal["not_started", "in_progress", "completed"]


@frozen
class ActivationBlocker:
    code: str
    message: str
    retryable: bool = False
    url: str | None = None


@frozen
class ActivationSource:
    source_product: str
    source_type: str
    enabled: bool = True


@frozen
class ActivationScout:
    skill_name: str = GENERAL_SCOUT
    run_interval_minutes: int = 1440
    run_cron_schedule: str | None = None


@frozen
class QuickActivationPlan:
    state: ActivationState
    can_activate: bool
    blockers: tuple[ActivationBlocker, ...]
    requested_project_id: int
    canonical_project_id: int
    activation_mode: ActivationMode
    automatic_implementation: bool | None
    sources: tuple[ActivationSource, ...]
    scanner_ids: tuple[UUID, ...]
    general_scout: ActivationScout
    setup_description: str
    billing_url: str
    inbox_url: str
    implementation_priority: str = "P1"
    billing_description: str = "Runs use your organization's existing Self-Driving plan and limits. Review billing."
    jobs: dict[str, str] | None = None
    first_report: dict[str, Any] | None = None
    error_code: str | None = None

    def draft(self) -> dict[str, Any]:
        return {
            "step": "github",
            "setup_mode": "quick",
            **({"activation_mode": "github_optional"} if self.activation_mode == "github_optional" else {}),
            "sources": [
                {"source_product": source.source_product, "source_type": source.source_type, "enabled": True}
                for source in self.sources
            ],
            "scanner_ids": [str(scanner_id) for scanner_id in self.scanner_ids],
            "suggestions": [
                {
                    "id": f"builtin:{GENERAL_SCOUT}",
                    "kind": "canonical",
                    "skill_name": GENERAL_SCOUT,
                    "title": "General scout",
                    "why_here": "Explore available data and investigate what needs your attention.",
                    "description": "",
                    "draft_body": "",
                    "proposed_config": {
                        "run_interval_minutes": self.general_scout.run_interval_minutes,
                        "run_cron_schedule": self.general_scout.run_cron_schedule,
                        "emit": True,
                    },
                    "gap": True,
                    "confidence": "medium",
                }
            ],
            "automatic_implementation": self.automatic_implementation,
            "implementation_priority": "P1",
        }


@frozen
class QuickActivationOutcome:
    preview: QuickActivationPlan
    status_code: int = 200


@frozen
class ActivationScanners:
    ids: tuple[UUID, ...] = ()
    blockers: tuple[ActivationBlocker, ...] = ()


def _has_scopes(scopes: Sequence[str] | None, required: set[str]) -> bool:
    if scopes is None or "*" in scopes:
        return True
    held = set(scopes)
    held.update(f"{scope.removesuffix(':write')}:read" for scope in scopes if scope.endswith(":write"))
    return required.issubset(held)


def _available_sources(team: Team) -> tuple[ActivationSource, ...]:
    events = set(
        EventDefinition.objects.filter(
            Q(project_id=team.project_id) | Q(project_id__isnull=True, team_id=team.id),
            name__in=("$exception", "$ai_generation", "$ai_trace", "$pageview", "$autocapture"),
            last_seen_at__gt=timezone.now() - timedelta(days=STALE_EVENT_DAYS),
        ).values_list("name", flat=True)
    )
    products = (
        (
            "error_tracking",
            ("issue_created", "issue_reopened", "issue_spiking"),
            "$exception" in events or issue_exists(team.id),
        ),
        ("health_checks", ("health_issue",), bool(team.ingested_event)),
        ("conversations", ("ticket",), team.conversations_enabled),
        ("llm_analytics", ("evaluation_report",), bool(events & {"$ai_generation", "$ai_trace"})),
        ("analytics", ("anomaly_investigation",), bool(events & {"$pageview", "$autocapture"})),
    )
    return tuple(
        ActivationSource(source_product=product, source_type=source_type)
        for product, source_types, available in products
        if available
        for source_type in source_types
    )


def _stored_blockers(
    team: Team, canonical_team: Team, scout: SignalScoutConfig | None, sources: Sequence[ActivationSource]
) -> list[ActivationBlocker]:
    blockers: list[ActivationBlocker] = []
    selected = Q(team_id=canonical_team.id, source_product="signals_scout", source_type="cross_source_issue")
    for source in sources:
        selected |= Q(team_id=team.id, source_product=source.source_product, source_type=source.source_type)
    if SignalSourceConfig.objects.filter(selected, enabled=False).exists():
        blockers.append(
            ActivationBlocker(
                code="sources_paused",
                message="Some sources are paused. Review your Self-Driving settings before activating.",
            )
        )
    if scout is not None and (
        scout.lifecycle_locked
        or scout.status == SignalScoutConfig.Status.PAUSED_BY_SYSTEM
        or (not scout.enabled and any((scout.status_changed_by_id, scout.enabled_by_id, scout.last_run_at)))
        or (not scout.emit and scout.enabled_by_id is not None)
    ):
        blockers.append(
            ActivationBlocker(
                code="scout_paused",
                message="The general scout is paused or locked. Review it in Self-Driving settings.",
            )
        )
    return blockers


def _write_access_blockers(
    team: Team, canonical_team: Team, user: User, scopes: Sequence[str] | None
) -> list[ActivationBlocker]:
    blockers: list[ActivationBlocker] = []
    if not _has_scopes(scopes, {"task:write", "signal_scout:write", "llm_skill:write"}):
        blockers.append(
            ActivationBlocker(
                code="missing_scope", message="Reconnect with permission to configure Self-Driving and scouts."
            )
        )
    requested_access = UserAccessControl(user=user, team=team)
    canonical_access = UserAccessControl(user=user, team=canonical_team)
    resources: tuple[Literal["task", "signal_scout", "llm_skill"], ...] = ("task", "signal_scout", "llm_skill")
    if not requested_access.check_access_level_for_resource("task", "editor") or not all(
        canonical_access.check_access_level_for_resource(resource, "editor") for resource in resources
    ):
        blockers.append(
            ActivationBlocker(
                code="permission_denied",
                message="Ask a project admin for permission to configure Self-Driving and scouts.",
            )
        )
    return blockers


def _completed_plan(team: Team, config: SignalTeamConfig, inbox_url: str, billing_url: str) -> QuickActivationPlan:
    state = config.onboarding or {}
    draft = state.get("draft") or {}
    scout = SignalScoutConfig.objects.for_team(team.parent_team_id or team.id).filter(skill_name=GENERAL_SCOUT).first()
    return QuickActivationPlan(
        state="completed",
        can_activate=False,
        blockers=(),
        requested_project_id=team.id,
        canonical_project_id=team.parent_team_id or team.id,
        activation_mode="github_optional" if draft.get("activation_mode") == "github_optional" else "standard",
        automatic_implementation=config.autostart_enabled,
        sources=tuple(ActivationSource(**source) for source in draft.get("sources", [])),
        scanner_ids=tuple(UUID(scanner_id) for scanner_id in draft.get("scanner_ids", [])),
        general_scout=ActivationScout(
            run_interval_minutes=scout.run_interval_minutes if scout else 1440,
            run_cron_schedule=scout.run_cron_schedule if scout else None,
        ),
        setup_description="Onboarding is complete. Existing settings are preserved; retrying only resubmits unfinished background work.",
        billing_url=billing_url,
        inbox_url=inbox_url,
        implementation_priority=config.default_autostart_priority,
        jobs=state.get("jobs"),
        first_report=first_report_state(team.parent_team_id or team.id) or None,
    )


def _repository_blockers(team: Team, *, pilot: bool, inbox_url: str) -> list[ActivationBlocker]:
    if pilot:
        return []
    try:
        if InboxOnboardingReconciler(team.id).has_repository():
            return []
    except APIException:
        return [
            ActivationBlocker(
                code="github_unavailable",
                message="GitHub access could not be checked. Try again shortly.",
                retryable=True,
            )
        ]
    return [
        ActivationBlocker(
            code="github_required",
            message="Connect GitHub with access to a repository before activating.",
            url=inbox_url,
        )
    ]


def _scout_blockers(
    canonical_team: Team,
    scout: SignalScoutConfig | None,
    *,
    pilot: bool,
    withheld: set[str],
    inbox_url: str,
    billing_url: str,
) -> list[ActivationBlocker]:
    blockers: list[ActivationBlocker] = []
    if (
        GENERAL_SCOUT in withheld
        or GENERAL_SCOUT not in canonical_skill_names()
        or canonical_deprecation_for(GENERAL_SCOUT)
    ):
        blockers.append(
            ActivationBlocker(
                code="scout_unavailable",
                message="The general scout is not available for this project. Try setup in the inbox.",
                url=inbox_url,
            )
        )
    skill_origin = registered_scout_skill_origin(canonical_team.id, GENERAL_SCOUT)
    if skill_origin == "custom" or (scout is not None and skill_origin is None):
        blockers.append(
            ActivationBlocker(
                code="scout_customized",
                message="The general scout has been customized. Review setup in the inbox.",
                url=inbox_url,
            )
        )
    if (scout is None or not scout.enabled) and enabled_scout_count(
        canonical_team.id, exclude_skill=GENERAL_SCOUT
    ) >= max_enabled_scouts_for_team(canonical_team.id):
        blockers.append(
            ActivationBlocker(
                code="scout_limit",
                message="This project reached its enabled scout limit. Review your scouts before activating.",
                url=inbox_url,
            )
        )
    if rejection := check_spend_gates(canonical_team, capture_analytics=False):
        blockers.append(
            ActivationBlocker(code=rejection.reason, message=rejection.detail, retryable=True, url=billing_url)
        )
    if not pilot or team_is_enrolled_after_onboarding(canonical_team.id, github_optional=False):
        if rejection := check_fleet_gates(canonical_team.id):
            if rejection.reason != "not_enrolled":
                blockers.append(ActivationBlocker(code=rejection.reason, message=rejection.detail, retryable=True))
    return blockers


def _scanner_selection(team: Team, user: User, scopes: Sequence[str] | None, inbox_url: str) -> ActivationScanners:
    if not has_enabled_onboarding_scanners(team):
        return ActivationScanners()
    if not _has_scopes(scopes, {"replay_scanner:read"}):
        return ActivationScanners(
            blockers=(
                ActivationBlocker(
                    code="scanner_read_scope",
                    message="Reconnect with permission to read replay scanners before activating.",
                ),
            )
        )
    scanners = enabled_onboarding_scanners(team, user)
    blockers: list[ActivationBlocker] = []
    if len(scanners) > 100:
        blockers.append(
            ActivationBlocker(
                code="scanner_limit",
                message="This project has too many replay scanners for quick activation. Use setup in the inbox.",
                url=inbox_url,
            )
        )
    if any(not scanner.emits_signals for scanner in scanners) and (
        not _has_scopes(scopes, {"replay_scanner:write", "session_recording:read"})
        or not UserAccessControl(user=user, team=team).check_access_level_for_resource("session_recording", "viewer")
        or any(not scanner.emits_signals and not scanner.can_edit for scanner in scanners)
    ):
        blockers.append(
            ActivationBlocker(
                code="scanner_write_permission",
                message="You need permission to edit replay scanners and read recordings before activating.",
            )
        )
    return ActivationScanners(ids=tuple(scanner.id for scanner in scanners), blockers=tuple(blockers))


def preview_quick_activation(team: Team, user: User, scopes: Sequence[str] | None) -> QuickActivationPlan:
    canonical_team = team.parent_team or team
    origin = settings.SITE_URL.rstrip("/")
    inbox_url = f"{origin}/project/{team.id}/inbox"
    billing_url = f"{origin}/organization/billing"
    config = SignalTeamConfig.objects.filter(team_id=team.id).first()
    state = (config.onboarding or {}) if config else {}
    if state.get("completed_at"):
        assert config is not None
        return _completed_plan(team, config, inbox_url, billing_url)
    sources = _available_sources(team)
    blockers = _write_access_blockers(team, canonical_team, user, scopes)
    if state.get("draft"):
        blockers.append(
            ActivationBlocker(
                code="setup_in_progress",
                message="You have saved setup choices. Finish setup in Self-Driving.",
                url=inbox_url,
            )
        )
    if canonical_team.organization.is_ai_data_processing_approved is not True:
        blockers.append(
            ActivationBlocker(
                code="ai_consent_required",
                message="Approve AI data processing in organization settings first.",
                url=f"{origin}/settings/organization#ai-data-processing",
            )
        )
    pilot = ResearchAccessPolicy.enabled_for_project(canonical_team)
    pricing = onboarding_usage_based_pricing(team, user)
    automatic = False if pilot else (not pricing if pricing is not None else None)
    if pricing is None:
        blockers.append(
            ActivationBlocker(
                code="pricing_unavailable",
                message="Could not check your Self-Driving settings. Try again shortly.",
                retryable=True,
            )
        )
    if not team_is_enrolled_after_onboarding(canonical_team.id, github_optional=pilot):
        blockers.append(
            ActivationBlocker(
                code="not_enrolled",
                message="Self-Driving is not available for this project. Open the inbox to check availability.",
                url=inbox_url,
            )
        )
    blockers.extend(_repository_blockers(team, pilot=pilot, inbox_url=inbox_url))
    layers, withheld = resolve_sync_seed_inputs(canonical_team.id)
    scout = SignalScoutConfig.objects.for_team(canonical_team.id).filter(skill_name=GENERAL_SCOUT).first()
    blockers.extend(_stored_blockers(team, canonical_team, scout, sources))
    blockers.extend(
        _scout_blockers(
            canonical_team, scout, pilot=pilot, withheld=withheld, inbox_url=inbox_url, billing_url=billing_url
        )
    )
    scanners = _scanner_selection(team, user, scopes, inbox_url)
    blockers.extend(scanners.blockers)
    _, seed_interval = _resolve_seed_posture(layers)
    return QuickActivationPlan(
        state="in_progress" if state.get("draft") else "not_started",
        can_activate=not blockers,
        blockers=tuple(blockers),
        requested_project_id=team.id,
        canonical_project_id=canonical_team.id,
        activation_mode="github_optional" if pilot else "standard",
        automatic_implementation=automatic,
        sources=sources,
        scanner_ids=scanners.ids,
        general_scout=ActivationScout(
            run_interval_minutes=scout.run_interval_minutes if scout else seed_interval or 1440,
            run_cron_schedule=scout.run_cron_schedule if scout else None,
        ),
        setup_description=(
            "Enable available signal sources, findings from existing replay scanners, and the general scout."
            + (
                f" The scout fleet belongs to parent project {canonical_team.id}, where automatic pull requests will be turned off."
                f" The automatic implementation setting shown here applies to selected project {team.id}."
                if canonical_team.id != team.id
                else ""
            )
        ),
        billing_url=billing_url,
        inbox_url=inbox_url,
    )


def _lock_activation_configs(team: Team, canonical_team: Team) -> dict[int, SignalTeamConfig]:
    for owner in sorted({team.id: team, canonical_team.id: canonical_team}.values(), key=lambda item: item.id):
        get_or_create_team_extension(owner, SignalTeamConfig)
    return {
        config.team_id: config
        for config in SignalTeamConfig.objects.select_for_update()
        .filter(team_id__in={team.id, canonical_team.id})
        .order_by("team_id")
    }


def _validate_stored_activation(
    team: Team, canonical_team: Team, config: SignalTeamConfig, plan: QuickActivationPlan
) -> None:
    if (config.onboarding or {}).get("draft"):
        raise ValueError("Setup choices changed. Review activation again.")
    scout = (
        SignalScoutConfig.objects.for_team(canonical_team.id)
        .select_for_update()
        .filter(skill_name=GENERAL_SCOUT)
        .first()
    )
    list(
        SignalSourceConfig.objects.select_for_update()
        .filter(team_id__in={team.id, canonical_team.id})
        .values_list("pk", flat=True)
    )
    if _stored_blockers(team, canonical_team, scout, plan.sources):
        raise ValueError("Self-Driving settings changed. Review activation again.")
    if registered_scout_skill_origin(canonical_team.id, GENERAL_SCOUT) == "custom":
        raise ValueError("The general scout changed. Review activation again.")


def _enable_sources(plan: QuickActivationPlan, user: User) -> None:
    for source in plan.sources:
        source_config, created = SignalSourceConfig.objects.get_or_create(
            team_id=plan.requested_project_id,
            source_product=source.source_product,
            source_type=source.source_type,
            defaults={"enabled": True, "created_by": user},
        )
        if not source_config.enabled:
            raise ValueError("A source was paused. Review activation again.")
        if created and source.source_product == "error_tracking" and source.source_type == "issue_created":
            transaction.on_commit(lambda: trigger_error_tracking_backfill(plan.requested_project_id))
    scout_source, _ = SignalSourceConfig.objects.get_or_create(
        team_id=plan.canonical_project_id,
        source_product="signals_scout",
        source_type="cross_source_issue",
        defaults={"enabled": True, "created_by": user},
    )
    if not scout_source.enabled:
        raise ValueError("Scout findings were paused. Review activation again.")


def _enable_general_scout(team: Team, request: Request, plan: QuickActivationPlan, max_enabled_scouts: int) -> None:
    from products.signals.backend.scout_harness.views import (  # noqa: PLC0415 - reuse the guarded write path without importing scout views for previews
        _upsert_scout_config,
        guard_scout_lifecycle_fields,
    )

    canonical_team = team.parent_team or team
    tunables = {
        "enabled": True,
        "emit": True,
        "run_interval_minutes": plan.general_scout.run_interval_minutes,
        "run_cron_schedule": plan.general_scout.run_cron_schedule,
    }
    scout = (
        SignalScoutConfig.objects.for_team(canonical_team.id)
        .select_for_update()
        .filter(skill_name=GENERAL_SCOUT)
        .first()
    )
    guard_scout_lifecycle_fields(
        request=request,
        team=canonical_team,
        skill_name=GENERAL_SCOUT,
        config=scout,
        requested=tunables,
        action="create",
    )
    _upsert_scout_config(
        team_id=canonical_team.id,
        skill_name=GENERAL_SCOUT,
        tunables=tunables,
        request=request,
        serializer_context={"request": request, "get_team": lambda: canonical_team, "project_id": team.project_id},
        max_enabled_scouts=max_enabled_scouts,
    )


def activate_quick_setup(
    onboarding: InboxOnboarding,
    request: Request,
    scopes: Sequence[str] | None,
    *,
    expected_activation_mode: ActivationMode,
    expected_automatic_implementation: bool,
) -> QuickActivationOutcome:
    team = onboarding.team
    user = onboarding.user
    plan = preview_quick_activation(team, user, scopes)
    if plan.state == "completed":
        onboarding.retry_activation_jobs()
        return QuickActivationOutcome(preview=plan)
    if (plan.activation_mode, plan.automatic_implementation) != (
        expected_activation_mode,
        expected_automatic_implementation,
    ):
        return QuickActivationOutcome(preview=replace(plan, error_code="activation_changed"), status_code=409)
    if not plan.can_activate:
        return QuickActivationOutcome(preview=replace(plan, error_code="activation_blocked"), status_code=409)
    draft = plan.draft()
    preparation = onboarding.prepare_completion(draft)
    canonical_team = team.parent_team or team
    max_enabled_scouts = max_enabled_scouts_for_team(canonical_team.id)
    seed_inputs = resolve_sync_seed_inputs(canonical_team.id)
    if GENERAL_SCOUT in seed_inputs[1]:
        raise ValueError("The general scout is no longer available. Review activation again.")
    from products.signals.backend.scout_harness.fleet_sync import (
        materialize_scout_fleet,  # noqa: PLC0415 - keeps fleet writes off the preview import path
    )

    with transaction.atomic():
        configs = _lock_activation_configs(team, canonical_team)
        config = configs[team.id]
        if (config.onboarding or {}).get("completed_at"):
            onboarding.retry_activation_jobs()
            return QuickActivationOutcome(preview=_completed_plan(team, config, plan.inbox_url, plan.billing_url))
        _validate_stored_activation(team, canonical_team, config, plan)
        for config in configs.values():
            config.autostart_enabled = False
            config.save(update_fields=["autostart_enabled", "updated_at"])
        materialize_scout_fleet(canonical_team, surface="onboarding", seed_inputs=seed_inputs)
        if registered_scout_skill_origin(canonical_team.id, GENERAL_SCOUT) != "canonical":
            raise ValueError("The general scout could not be prepared. Try setup in the inbox.")
        _enable_sources(plan, user)
        enable_onboarding_scanner_signals(
            team,
            user,
            plan.scanner_ids,
            credential_can_write=_has_scopes(scopes, {"replay_scanner:write", "session_recording:read"}),
        )
        _enable_general_scout(team, request, plan, max_enabled_scouts)
        config = configs[team.id]
        config.onboarding = {**(config.onboarding or {}), "entrypoint": ACTIVATION_ENTRYPOINT}
        config.save(update_fields=["onboarding", "updated_at"])
        onboarding.complete_prepared(draft, preparation)
        config.refresh_from_db()
    return QuickActivationOutcome(preview=_completed_plan(team, config, plan.inbox_url, plan.billing_url))
