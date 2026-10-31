from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.ph_client import ph_scoped_capture
from posthog.temporal.common.client import sync_connect

from products.signals.backend.constants import FIRST_REPORT_SCOUT
from products.signals.backend.first_report_experiment import (
    FIRST_REPORT_SCOUT_VARIANTS,
    capture_first_report_exposure,
    resolve_first_report_experiment,
)
from products.signals.backend.first_report_scout import (
    build_first_report_context,
    first_report_state,
    set_first_report_state,
)
from products.signals.backend.first_report_scout_types import FirstReportStatus
from products.signals.backend.models import SignalScoutConfig, SignalTeamConfig
from products.signals.backend.onboarding_analytics import InboxOnboardingAnalytics
from products.signals.backend.onboarding_completion import InboxOnboardingReconciler
from products.signals.backend.onboarding_state import is_quick_setup
from products.signals.backend.scout_harness.run_gates import check_fleet_gates, check_run_in_flight, check_spend_gates
from products.signals.backend.scout_harness.suggestions import read_suggestion_settings, suggestions_allowed_for_team
from products.signals.backend.temporal.agentic.scout_scheduler import start_onboarding_signals_scout_run
from products.signals.backend.temporal.agentic.scout_suggestions import start_manual_scout_suggestions_run


class InboxOnboardingActivation:
    def __init__(self, team_id: int) -> None:
        self.team_id = team_id

    def _capture_status(self, config: SignalTeamConfig, job: str, status: str, reason: str | None) -> None:
        user = User.objects.filter(pk=(config.onboarding or {}).get("activated_by")).first()
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=str(config.team.uuid),
                event="self-driving onboarding job status changed",
                groups=groups(team=config.team),
                properties={
                    **InboxOnboardingAnalytics.properties(config, user),
                    "job": job,
                    "status": status,
                    "reason": reason,
                    "experiment_variant": (config.onboarding or {}).get("first_report_variant"),
                    "first_report_outcome": first_report_state(config.team.parent_team_id or self.team_id).get("status")
                    if job == "scout"
                    and (config.onboarding or {}).get("first_report_variant") in FIRST_REPORT_SCOUT_VARIANTS
                    else None,
                },
            )

    def _record_status(self, job: str, status: str, reason: str | None = None) -> None:
        with transaction.atomic():
            config = SignalTeamConfig.objects.select_for_update().get(team_id=self.team_id)
            state = config.onboarding or {}
            if state.get("jobs", {}).get(job) == status:
                return
            config.onboarding = {**state, "jobs": {**state.get("jobs", {}), job: status}}
            config.save(update_fields=["onboarding", "updated_at"])
            transaction.on_commit(lambda: self._capture_status(config, job, status, reason), robust=True)

    def _start_first_report(self, team: Team, state: dict[str, Any], *, final_attempt: bool) -> bool:
        experiment = resolve_first_report_experiment(team, raise_on_error=True)
        # Every arm passes the same gates before exposure, so the arms share one denominator.
        # A control project then gets the activation it would have had without the experiment.
        runs_scout = experiment is not None and experiment.runs_scout

        def stop(status: FirstReportStatus) -> bool:
            if state.get("first_report_variant") in FIRST_REPORT_SCOUT_VARIANTS:
                set_first_report_state(team.id, status)
            return False if runs_scout else self._start_default_scout(team, state)

        if experiment is None:
            return stop(FirstReportStatus.INCOMPLETE)
        if (
            not InboxOnboardingReconciler.scouts_can_emit(team.id)
            or check_fleet_gates(team.id)
            or check_spend_gates(team)
        ):
            return stop(FirstReportStatus.INCOMPLETE)
        if runs_scout and check_run_in_flight(team.id, FIRST_REPORT_SCOUT):
            return True
        acting_user_id = state.get("activated_by")
        user = (
            team.all_users_with_access().filter(pk=acting_user_id, is_active=True).first() if acting_user_id else None
        )
        if user is None:
            return stop(FirstReportStatus.INCOMPLETE)
        context = build_first_report_context(team, user)
        if not context.has_data():
            if not context.data_is_unknown():
                return stop(FirstReportStatus.NO_DATA)
            if not final_attempt:
                raise RuntimeError("Project data availability is unknown")
            return stop(FirstReportStatus.INCOMPLETE)
        capture_first_report_exposure(team, experiment)
        if not runs_scout:
            return self._start_default_scout(team, state)
        scout, _ = SignalScoutConfig.objects.for_team(team.id).get_or_create(
            team_id=team.id,
            skill_name=FIRST_REPORT_SCOUT,
            defaults={
                "enabled": False,
                "emit": True,
                "created_by": user,
                "enabled_by": user,
                "write_scopes": [],
            },
        )
        set_first_report_state(team.id, FirstReportStatus.PENDING, activation_team_id=self.team_id)
        start_onboarding_signals_scout_run(
            sync_connect(), team_id=team.id, skill_name=scout.skill_name, run_note=context.prompt_context()
        )
        return True

    def _start_default_scout(self, team: Team, state: dict[str, Any]) -> bool:
        return is_quick_setup(state) and self._start_general_scout(team)

    def _start_general_scout(self, team: Team) -> bool:
        scout = (
            SignalScoutConfig.objects.for_team(team.id)
            .filter(skill_name="signals-scout-general", enabled=True, emit=True)
            .first()
        )
        if not scout or check_fleet_gates(team.id) or check_spend_gates(team):
            return False
        if check_run_in_flight(team.id, scout.skill_name):
            return True
        start_onboarding_signals_scout_run(sync_connect(), team_id=team.id, skill_name=scout.skill_name)
        SignalScoutConfig.objects.for_team(team.id).filter(pk=scout.pk, last_run_at__isnull=True).update(
            last_run_at=timezone.now()
        )
        return True

    def _start_recommendations(self, team: Team, acting_user_id: int | None) -> bool:
        if not suggestions_allowed_for_team(read_suggestion_settings(), team.id):
            return False
        start_manual_scout_suggestions_run(
            sync_connect(), team_id=team.id, acting_user_id=acting_user_id, onboarding=True
        )
        return True

    def run(self, job: str, *, final_attempt: bool = True) -> None:
        if job not in ("scout", "recommendations"):
            raise ValueError("Unknown onboarding job")
        config = SignalTeamConfig.objects.select_related("team__parent_team", "team__organization").get(
            team_id=self.team_id
        )
        state = config.onboarding or {}
        if not state.get("completed_at"):
            return
        if state.get("jobs", {}).get(job) in ("started", "skipped"):
            return
        team = config.team.parent_team or config.team
        enrolled = job == "scout" and bool(state.get("first_report_variant"))
        first_report = state.get("first_report_variant") in FIRST_REPORT_SCOUT_VARIANTS
        if team.organization.is_ai_data_processing_approved is not True:
            if enrolled and first_report:
                set_first_report_state(team.id, FirstReportStatus.INCOMPLETE)
            self._record_status(job, "skipped", "ai_consent_required")
            return
        try:
            if enrolled:
                started = self._start_first_report(team, state, final_attempt=final_attempt)
            elif job == "scout":
                started = self._start_default_scout(team, state)
            else:
                started = self._start_recommendations(team, state.get("activated_by"))
        except Exception:
            if enrolled and first_report and final_attempt:
                set_first_report_state(team.id, FirstReportStatus.INCOMPLETE)
            self._record_status(job, "failed" if final_attempt else "pending", "dispatch_error")
            raise
        self._record_status(job, "started" if started else "skipped", None if started else "not_eligible")
