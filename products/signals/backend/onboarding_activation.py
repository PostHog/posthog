from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from posthog.models.team.team import Team
from posthog.temporal.common.client import sync_connect

from products.signals.backend.models import SignalScoutConfig, SignalTeamConfig
from products.signals.backend.scout_harness.run_gates import check_fleet_gates, check_run_in_flight, check_spend_gates
from products.signals.backend.scout_harness.suggestions import read_suggestion_settings, suggestions_allowed_for_team
from products.signals.backend.temporal.agentic.scout_scheduler import start_onboarding_signals_scout_run
from products.signals.backend.temporal.agentic.scout_suggestions import start_manual_scout_suggestions_run


class InboxOnboardingActivation:
    def __init__(self, team_id: int) -> None:
        self.team_id = team_id

    def _record_status(self, job: str, status: str) -> None:
        with transaction.atomic():
            config = SignalTeamConfig.objects.select_for_update().get(team_id=self.team_id)
            state = config.onboarding or {}
            config.onboarding = {**state, "jobs": {**state.get("jobs", {}), job: status}}
            config.save(update_fields=["onboarding", "updated_at"])

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

    def run(self, job: str) -> None:
        if job not in ("scout", "recommendations"):
            raise ValueError("Unknown onboarding job")
        config = SignalTeamConfig.objects.select_related("team__parent_team", "team__organization").get(
            team_id=self.team_id
        )
        state = config.onboarding or {}
        if state.get("variant") != "quick" or not state.get("completed_at"):
            return
        if state.get("jobs", {}).get(job) in ("started", "skipped"):
            return
        team = config.team.parent_team or config.team
        if team.organization.is_ai_data_processing_approved is not True:
            self._record_status(job, "skipped")
            return
        try:
            started = (
                self._start_scout(team)
                if job == "scout"
                else self._start_recommendations(team, state.get("activated_by"))
            )
        except Exception:
            self._record_status(job, "failed")
            raise
        self._record_status(job, "started" if started else "skipped")
