from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from posthog.cloud_utils import is_cloud
from posthog.event_usage import report_user_action
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.transactional_email import is_transactional_email_configured

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.facade.api import signal_emitting_scanner_ids
from products.signals.backend.first_report_completion import first_report_completion_notifications_enabled
from products.signals.backend.first_report_experiment import (
    FIRST_REPORT_SCOUT_VARIANTS,
    resolve_first_report_experiment,
)
from products.signals.backend.first_report_notification import register_first_report_notification
from products.signals.backend.first_report_scout import first_report_state
from products.signals.backend.first_report_scout_types import FirstReportStatus
from products.signals.backend.github_optional import GITHUB_OPTIONAL_ACTIVATION, ResearchAccessPolicy
from products.signals.backend.models import (
    AutonomyPriority,
    InboxOnboardingSetupMode,
    SignalFirstReportNotification,
    SignalScoutConfig,
    SignalScoutSuggestionSet,
    SignalSourceConfig,
    SignalTeamConfig,
    signal_source_product_choices,
)
from products.signals.backend.onboarding_analytics import InboxOnboardingAnalytics
from products.signals.backend.onboarding_completion import InboxOnboardingReconciler
from products.signals.backend.onboarding_scouts import InboxOnboardingScouts
from products.signals.backend.onboarding_state import is_quick_setup
from products.signals.backend.report_content_gates import team_first_report_email_enabled
from products.signals.backend.scout_harness.create_access import can_create_scout
from products.signals.backend.scout_harness.team_limits import withheld_skills_for_team

if TYPE_CHECKING:
    from django.utils.functional import Promise


class InboxOnboardingValidationError(ValueError):
    pass


class InboxOnboardingPermissionError(PermissionError):
    pass


def onboarding_source_products() -> Sequence[tuple[str, str | Promise]]:
    return signal_source_product_choices()


def onboarding_source_types() -> Sequence[tuple[str, str | Promise]]:
    return SignalSourceConfig.SourceType.choices


def onboarding_priorities() -> Sequence[tuple[str, str | Promise]]:
    return AutonomyPriority.choices


def onboarding_setup_modes() -> Sequence[tuple[str, str | Promise]]:
    return InboxOnboardingSetupMode.choices


def onboarding_first_report_statuses() -> Sequence[tuple[str, str | Promise]]:
    return FirstReportStatus.choices


def can_create_onboarding_scout(user: User, team: Team) -> bool:
    return can_create_scout(user, team)


class InboxOnboarding:
    def __init__(self, team: Team, user: User, authorize_scouts: Callable[[bool], None]) -> None:
        self.team = team
        self.team_id = team.id
        self.user = user
        self.authorize_scouts = authorize_scouts

    def _state(self, config: SignalTeamConfig) -> dict[str, Any]:
        state = config.onboarding or {}
        if (
            self.team.parent_team_id
            or state.get("first_report")
            or state.get("jobs", {}).get("scout")
            or any((state.get("draft") or {}).get(key) for key in ("suggestions", "activation_scouts"))
        ):
            self.authorize_scouts(False)
        jobs = dict(state.get("jobs", {}))
        if (
            jobs.get("recommendations") == "started"
            and state.get("completed_at")
            and SignalScoutSuggestionSet.objects.filter(
                team_id=self.team.parent_team_id or self.team_id,
                status=SignalScoutSuggestionSet.Status.FAILED,
                last_requested_at__gte=state["completed_at"],
                last_completed_at__gte=F("last_requested_at"),
            ).exists()
        ):
            jobs["recommendations"] = "failed"
        return {
            "github_optional_available": ResearchAccessPolicy.enabled(self.team_id),
            "draft": state.get("draft"),
            "completed_at": state.get("completed_at"),
            **({"jobs": jobs} if "jobs" in state else {}),
            "first_report": first_report_state(self.team.parent_team_id or self.team_id)
            or (
                {"status": "pending"}
                if state.get("first_report_variant") in FIRST_REPORT_SCOUT_VARIANTS and jobs.get("scout") == "pending"
                else None
            ),
            "first_report_completion_notification": bool(
                state.get("first_report_variant") in FIRST_REPORT_SCOUT_VARIANTS
                and state.get("activated_by") == self.user.pk
                and first_report_completion_notifications_enabled(self.team.parent_team or self.team, self.user)
            ),
            "first_report_notification_email": (
                self.user.email
                if is_cloud()
                and is_transactional_email_configured()
                and team_first_report_email_enabled(self.team_id)
                and SignalFirstReportNotification.objects.for_team(self.team_id)
                .filter(activated_by=self.user, queued_at__isnull=True, cancelled_at__isnull=True)
                .exists()
                else None
            ),
        }

    def state(self) -> dict[str, Any]:
        return self._state(get_or_create_team_extension(self.team, SignalTeamConfig))

    def expose(self) -> dict[str, Any]:
        config = get_or_create_team_extension(self.team, SignalTeamConfig)
        with transaction.atomic():
            config = SignalTeamConfig.objects.select_for_update().get(pk=config.pk, team_id=self.team_id)
            state = config.onboarding or {}
            if not state.get("exposed_at"):
                config.onboarding = {
                    **state,
                    "exposed_at": timezone.now().isoformat(),
                    "exposed_by": self.user.pk,
                }
                config.save(update_fields=["onboarding", "updated_at"])
                transaction.on_commit(lambda: self._report_exposure(self.user, config), robust=True)
        return self._state(config)

    def _validate_pilot(self, draft: dict[str, Any]) -> bool:
        if draft.get("activation_mode") != GITHUB_OPTIONAL_ACTIVATION:
            return False
        if not ResearchAccessPolicy.enabled(self.team_id):
            raise InboxOnboardingValidationError("The GitHub-optional pilot is not enabled for this project.")
        if draft["automatic_implementation"]:
            raise InboxOnboardingValidationError(
                "Activate without automatic implementation. You can enable it later in settings."
            )
        return True

    def save_draft(self, draft: dict[str, Any]) -> dict[str, Any]:
        self._validate_pilot(draft)
        config = get_or_create_team_extension(self.team, SignalTeamConfig)
        with transaction.atomic():
            config = SignalTeamConfig.objects.select_for_update().get(team_id=self.team_id, pk=config.pk)
            state = config.onboarding or {}
            if any(
                draft.get(key) or (state.get("draft") or {}).get(key) for key in ("suggestions", "activation_scouts")
            ):
                self.authorize_scouts(True)
            if not state.get("completed_at"):
                config.onboarding = {**state, "draft": draft}
                config.save(update_fields=["onboarding", "updated_at"])
        return self._state(config)

    def complete(self, draft: dict[str, Any]) -> dict[str, Any]:
        # Activation enqueues scout jobs after commit, so the scout write check has to pass before anything is saved.
        self.authorize_scouts(True)
        config = get_or_create_team_extension(self.team, SignalTeamConfig)
        if (config.onboarding or {}).get("completed_at"):
            self._enqueue_activation_jobs(config)
            return self._state(config)

        pilot = self._validate_pilot(draft)
        if pilot and self.team.parent_team_id:
            if not UserAccessControl(user=self.user, team=self.team.parent_team).check_access_level_for_resource(
                "task", "editor"
            ):
                raise InboxOnboardingPermissionError(
                    "Activating this pilot requires task editor access on the parent project."
                )
        if pilot:
            if not any(
                item["kind"] == "canonical" and item["skill_name"] == "signals-scout-general"
                for item in draft["suggestions"]
            ):
                raise InboxOnboardingValidationError("Quick activation requires the general scout.")

        if draft["suggestions"]:
            if not InboxOnboardingReconciler.scouts_can_emit(self.team.parent_team_id or self.team_id):
                raise InboxOnboardingValidationError(
                    "Scout findings are disabled. Enable the scout source before activating."
                )

        if not pilot and not InboxOnboardingReconciler(self.team_id).has_repository():
            raise InboxOnboardingValidationError("Connect GitHub with access to at least one repository.")

        selected_source = False
        for source in draft["sources"]:
            source_team_id = (
                self.team.parent_team_id or self.team_id
                if source["source_product"] == "signals_scout"
                else self.team_id
            )
            persisted = SignalSourceConfig.objects.filter(
                team_id=source_team_id,
                source_product=source["source_product"],
                source_type=source["source_type"],
            ).first()
            if (persisted is None and source["enabled"]) or (
                persisted is not None and persisted.enabled != source["enabled"]
            ):
                raise InboxOnboardingValidationError(
                    "Some signal source choices have not been saved. Retry activation."
                )
            selected_source = selected_source or source["enabled"]
        scanner_ids = [str(scanner_id) for scanner_id in draft["scanner_ids"]]
        if set(scanner_ids) != signal_emitting_scanner_ids(self.team_id, scanner_ids):
            raise InboxOnboardingValidationError("Replay vision has not been enabled. Retry activation.")
        for suggestion in draft["suggestions"]:
            if (
                not SignalScoutConfig.objects.for_team(self.team.parent_team_id or self.team_id)
                .filter(skill_name=suggestion["skill_name"], enabled=True, emit=True)
                .exists()
            ):
                raise InboxOnboardingValidationError("Some selected scouts have not been enabled. Retry activation.")
        if not (selected_source or draft["scanner_ids"] or draft["suggestions"]):
            raise InboxOnboardingValidationError("Select at least one usable signal source or scout.")

        scout_team_id = self.team.parent_team_id or self.team_id
        resume_operational_scouts = (
            scout_team_id == self.team_id
            or bool(draft["suggestions"])
            or any(source["source_product"] == "signals_scout" for source in draft["sources"])
        )
        withheld = withheld_skills_for_team(scout_team_id) if resume_operational_scouts else set()
        experiment = resolve_first_report_experiment(self.team.parent_team or self.team)
        user = self.user
        with transaction.atomic():
            config = SignalTeamConfig.objects.select_for_update().get(team_id=self.team_id, pk=config.pk)
            state = config.onboarding or {}
            if not state.get("completed_at"):
                if pilot and (parent_team := self.team.parent_team) is not None:
                    parent_config = get_or_create_team_extension(parent_team, SignalTeamConfig)
                    SignalTeamConfig.objects.filter(pk=parent_config.pk, team_id=scout_team_id).update(
                        autostart_enabled=False, updated_at=timezone.now()
                    )
                config.autostart_enabled = draft["automatic_implementation"]
                config.default_autostart_priority = draft["implementation_priority"]
                config.onboarding = {
                    **state,
                    "draft": draft,
                    "completed_at": timezone.now().isoformat(),
                    "activated_by": user.pk,
                }
                quick = pilot or is_quick_setup(config.onboarding)
                config.onboarding["jobs"] = {
                    "scout": "pending" if experiment or quick else "skipped",
                    "recommendations": "pending" if quick else "skipped",
                }
                if experiment:
                    config.onboarding["first_report_variant"] = experiment.variant
                config.save(
                    update_fields=["onboarding", "autostart_enabled", "default_autostart_priority", "updated_at"]
                )
                register_first_report_notification(team=self.team, user=user)
                if resume_operational_scouts:
                    InboxOnboardingScouts.resume(scout_team_id, withheld, lambda: self.authorize_scouts(True))
                transaction.on_commit(lambda: self._report_completion(user, config), robust=True)
                transaction.on_commit(lambda: self._enqueue_activation_jobs(config))
        return self._state(config)

    def _enqueue_activation_jobs(self, config: SignalTeamConfig) -> None:
        state = config.onboarding or {}
        from products.signals.backend.tasks import (
            launch_inbox_onboarding_job,  # noqa: PLC0415 - keep the Temporal graph off API route loading
        )

        for job, status in state.get("jobs", {}).items():
            if status in ("pending", "failed"):
                launch_inbox_onboarding_job.delay(self.team_id, job)

    def _report_completion(self, user: User, config: SignalTeamConfig) -> None:
        report_user_action(
            user,
            "self-driving onboarding completed",
            InboxOnboardingAnalytics.completion_properties(config, user),
            team=self.team,
            organization=self.team.organization,
        )

    def _report_exposure(self, user: User, config: SignalTeamConfig) -> None:
        report_user_action(
            user,
            "self-driving onboarding exposed",
            InboxOnboardingAnalytics.properties(config, user),
            team=self.team,
            organization=self.team.organization,
        )
