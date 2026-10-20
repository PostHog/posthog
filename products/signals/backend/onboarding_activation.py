from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.ph_client import ph_scoped_capture
from posthog.temporal.common.client import sync_connect

from products.signals.backend.models import SignalScoutConfig, SignalTeamConfig
from products.signals.backend.onboarding_analytics import InboxOnboardingAnalytics
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

    def _start_scout(self, team: Team) -> bool:
        scout = (
            SignalScoutConfig.objects.for_team(team.id)
            .filter(skill_name="signals-scout-general", enabled=True, emit=True)
            .first()
        )
        if scout is None or check_fleet_gates(team.id) or check_spend_gates(team):
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
        if state.get("variant") != "test-github" or not state.get("completed_at"):
            return
        if state.get("jobs", {}).get(job) in ("started", "skipped"):
            return
        team = config.team.parent_team or config.team
        if team.organization.is_ai_data_processing_approved is not True:
            self._record_status(job, "skipped", "ai_consent_required")
            return
        try:
            started = (
                self._start_scout(team)
                if job == "scout"
                else self._start_recommendations(team, state.get("activated_by"))
            )
        except Exception:
            self._record_status(job, "failed" if final_attempt else "pending", "dispatch_error")
            raise
        self._record_status(job, "started" if started else "skipped", None if started else "not_eligible")
