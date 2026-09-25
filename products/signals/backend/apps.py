from typing import TYPE_CHECKING

from django.apps import AppConfig

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.user import User


class SignalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.signals.backend"
    label = "signals"

    def ready(self) -> None:
        # activity_logging: consumes model_activity_signal to persist SignalScoutConfig and
        #   SignalTeamConfig audit-log entries (ModelActivityMixin only emits the signal; this
        #   is the consumer).
        # receivers: post_save receiver that closes a report's implementation PR on suppression/snooze.
        from . import (
            activity_logging,  # noqa: F401
            receivers,  # noqa: F401
        )

        receivers.connect_task_run_assignment_sync()
        self._register_signal_emission_gate()
        self._register_scout_skill_archive_guard()

    def _register_signal_emission_gate(self) -> None:
        """Let the data-import pipeline ask whether to emit signals for a source without
        importing this product (it depends on warehouse_sources). The gate impl is imported
        lazily so the registry/model stay off the django.setup() path.
        """
        from products.warehouse_sources.backend.facade.hooks import register_emit_signals_gate

        def _gate(team_id: int, source_type: str, schema_name: str, ai_data_processing_approved: bool) -> bool:
            from products.signals.backend.emission.gate import emit_signals_enabled  # noqa: PLC0415

            return emit_signals_enabled(team_id, source_type, schema_name, ai_data_processing_approved)

        register_emit_signals_gate(_gate)

    def _register_scout_skill_archive_guard(self) -> None:
        """Let the skills product refuse to archive a locked scout's skill without importing this
        one (the dependency runs the other way). Archiving is how a custom scout is removed, so a
        lock that guarded only the config would still let a non-owner stop the scout for good.
        The check is imported lazily so the harness stays off the django.setup() path.
        """
        from products.skills.backend.api.archive_guards import SkillArchiveRefused, register_skill_archive_guard

        def _guard(team: "Team", skill_name: str, user: "User", authenticator: object) -> None:
            from products.signals.backend.scout_harness.lifecycle_lock import (  # noqa: PLC0415
                ScoutLifecycleLocked,
                assert_can_archive_scout_skill,
            )

            try:
                assert_can_archive_scout_skill(team=team, skill_name=skill_name, user=user, authenticator=authenticator)
            except ScoutLifecycleLocked as err:
                raise SkillArchiveRefused(str(err)) from err

        register_skill_archive_guard(_guard)
