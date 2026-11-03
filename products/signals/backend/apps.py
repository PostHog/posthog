from typing import TYPE_CHECKING
from uuid import UUID

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
            implementation_pr_cache,
            receivers,  # noqa: F401
        )

        receivers.connect_task_run_assignment_sync()
        implementation_pr_cache.connect_implementation_pr_cache_receivers()
        self._register_task_spend_updates()
        self._register_signal_emission_gate()
        self._register_scout_skill_archive_guard()
        self._register_scout_skill_rename_hook()

    def _register_task_spend_updates(self) -> None:
        from products.tasks.backend.facade.task_run_signals import connect_task_run_cost_updated

        connect_task_run_cost_updated(_record_task_spend_delta, dispatch_uid="signals.task_spend_delta")

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

    def _register_scout_skill_rename_hook(self) -> None:
        """Let the skills product move or refuse a scout's config on rename without importing this one."""
        from products.skills.backend.api.archive_guards import (
            SkillRenameConflict,
            SkillRenameRefused,
            register_skill_rename_hook,
        )

        def _hook(team: "Team", skill_name: str, new_name: str, user: "User | None", authenticator: object) -> None:
            from products.signals.backend.scout_harness.lifecycle_lock import (  # noqa: PLC0415
                ScoutConfigNameTaken,
                ScoutLifecycleLocked,
                rename_scout_with_skill,
            )

            try:
                rename_scout_with_skill(
                    team=team, skill_name=skill_name, new_name=new_name, user=user, authenticator=authenticator
                )
            except ScoutLifecycleLocked as err:
                raise SkillRenameRefused(str(err)) from err
            except ScoutConfigNameTaken as err:
                raise SkillRenameConflict(str(err)) from err

        register_skill_rename_hook(_hook)


def _record_task_spend_delta(
    *, team_id: int, run_id: UUID, cost_delta_microusd: int, origin_product: str, **kwargs: object
) -> None:
    if origin_product not in {"signal_report", "signals_scout"}:
        return

    from products.signals.backend.spend import (
        record_task_cost_delta,  # noqa: PLC0415 — keeps accounting off Django startup
    )

    record_task_cost_delta(team_id=team_id, run_id=run_id, cost_delta_microusd=cost_delta_microusd)
