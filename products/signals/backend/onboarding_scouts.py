from __future__ import annotations

from collections.abc import Callable

from django.db import transaction

from products.signals.backend.models import SignalScoutConfig, SignalTeamConfig


class InboxOnboardingScouts:
    @staticmethod
    def record_pause(scout: SignalScoutConfig) -> None:
        assert scout.status_changed_at is not None
        with transaction.atomic():
            config, _ = SignalTeamConfig.objects.get_or_create(team_id=scout.team_id)
            config = SignalTeamConfig.objects.select_for_update().get(pk=config.pk, team_id=scout.team_id)
            state = config.onboarding or {}
            config.onboarding = {
                **state,
                "paused_operational_scouts": {
                    **state.get("paused_operational_scouts", {}),
                    str(scout.id): scout.status_changed_at.isoformat(),
                },
            }
            config.save(update_fields=["onboarding", "updated_at"])

    @staticmethod
    def resume(team_id: int, withheld_skill_names: set[str], authorize: Callable[[], None]) -> None:
        with transaction.atomic():
            config = SignalTeamConfig.objects.select_for_update().filter(team_id=team_id).first()
            if config is None:
                return
            state = config.onboarding or {}
            pauses = state.get("paused_operational_scouts", {})
            if not pauses:
                return
            candidates = (
                SignalScoutConfig.objects.for_team(team_id)
                .select_for_update()
                .filter(id__in=pauses, auto_pause_exempt_by_role=True, enabled=False)
            )
            scouts = [
                scout
                for scout in candidates
                if scout.status_changed_at and scout.status_changed_at.isoformat() == pauses[str(scout.id)]
            ]
            if scouts:
                authorize()
            for scout in scouts:
                if scout.skill_name in withheld_skill_names:
                    scout.status_changed_at = None
                    scout.save(update_fields=["status_changed_at", "updated_at"])
                else:
                    scout.enabled = True
                    scout.save(update_fields=["enabled", "updated_at"])
            config.onboarding = {key: value for key, value in state.items() if key != "paused_operational_scouts"}
            config.save(update_fields=["onboarding", "updated_at"])
