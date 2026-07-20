from __future__ import annotations

import logging
from datetime import timedelta

from django.apps import apps

from posthog.clickhouse.client import sync_execute

from products.posthog_ai.eval_harness.data_setup import (
    copy_demo_data_to_new_team,
    create_core_memory,
    ensure_master_demo_team,
)
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

from ee.clickhouse.materialized_columns.columns import (
    backfill_materialized_columns,
    get_materialized_columns,
    materialize,
)

from .django_env import NullDbBlocker

logger = logging.getLogger(__name__)


class SandboxedDemoData:
    """Run-scoped holder for master demo seed + per-case team factory.

    One instance per harness run: seeds the master Hedgebox team (or reuses
    a healthy one), then produces a fresh isolated ``CustomPromptSandboxContext``
    for every eval case via ``make_context(label)``. Each call copies the master
    into a brand-new org/team/user with its own core memory and tasks-API
    access, so concurrent eval cases can't pollute each other's state.
    """

    def __init__(
        self,
        master_team_id: int,
        django_db_blocker: NullDbBlocker,
        agent_model: str | None = None,
        agent_runtime: str | None = None,
        reasoning_effort: str | None = None,
        sandbox_timeout_seconds: int | None = None,
    ):
        self.master_team_id = master_team_id
        self._django_db_blocker = django_db_blocker
        self.agent_model = agent_model
        self.agent_runtime = agent_runtime
        self.reasoning_effort = reasoning_effort
        self.sandbox_timeout_seconds = sandbox_timeout_seconds

    def make_context(self, case_label: str) -> CustomPromptSandboxContext:
        CodeInvite = apps.get_model("tasks", "CodeInvite")
        CodeInviteRedemption = apps.get_model("tasks", "CodeInviteRedemption")

        org, team, user = copy_demo_data_to_new_team(self.master_team_id, self._django_db_blocker, label=case_label)
        create_core_memory(team, self._django_db_blocker)
        with self._django_db_blocker.unblock():
            invite, _ = CodeInvite.objects.get_or_create(code="eval-harness", max_redemptions=0, is_active=True)
            CodeInviteRedemption.objects.get_or_create(invite_code=invite, user=user, organization=org)
        logger.info("Case %r assigned team_id=%d user_id=%d", case_label, team.id, user.id)
        return CustomPromptSandboxContext(
            team_id=team.id,
            user_id=user.id,
            repository="posthog/hedgebox",
            model=self.agent_model,
            runtime_adapter=self.agent_runtime,
            reasoning_effort=self.reasoning_effort,
            # Under TEST=1, SANDBOX_TTL_SECONDS is 15 minutes — equal to the default
            # per-case timeout — so a slow Modal case would have its sandbox reaped
            # exactly as it was finishing. The modal provider passes a larger TTL here.
            sandbox_timeout_seconds=self.sandbox_timeout_seconds,
        )


# Event-level properties the error-tracking ``searchQuery`` test cases match on
# (see ``products/error_tracking/backend/hogql_queries/error_tracking_query_runner_utils.py``).
# These are stored as JSON arrays (``["TypeError"]``); without materialized
# columns the bare ``properties.$exception_types`` lookup goes through
# ``JSONExtractString`` which returns ``""`` for non-string JSON values, so
# ``searchQuery`` filtering on these properties silently never matches anything.
# Materializing and backfilling once per session makes the sandbox behave like
# prod for error-tracking searchQuery, including reused local ClickHouse state
# where the columns already exist but older demo rows still need values.
_EVAL_MATERIALIZED_EVENT_PROPERTIES: tuple[str, ...] = (
    "$exception_types",
    "$exception_values",
)


def _ensure_event_search_columns_materialized(django_db_blocker: NullDbBlocker) -> None:
    with django_db_blocker.unblock():
        existing_columns = get_materialized_columns("events")
        columns = []
        for property_name in _EVAL_MATERIALIZED_EVENT_PROPERTIES:
            column = existing_columns.get((property_name, "properties"))
            if column is None:
                column = materialize("events", property_name)
            columns.append(column)
        backfill_materialized_columns("events", columns, timedelta(days=180))


def ensure_demo_ready(
    *,
    blocker: NullDbBlocker,
    agent_model: str,
    agent_runtime: str,
    reasoning_effort: str | None,
    sandbox_timeout_seconds: int | None,
) -> SandboxedDemoData:
    """Seed the master Hedgebox team (once) and expose a per-case context factory."""
    master_team_id = ensure_master_demo_team(blocker)
    _ensure_event_search_columns_materialized(blocker)
    with blocker.unblock():
        rows = sync_execute(
            "SELECT event, count() FROM events WHERE team_id = %(team_id)s GROUP BY event ORDER BY 2 DESC LIMIT 20",
            {"team_id": master_team_id},
        )
    logger.info("Master demo ready: team_id=%d event_counts=%s", master_team_id, rows)
    logger.info("Sandboxed eval agent pinned to model=%r runtime=%r", agent_model, agent_runtime)

    return SandboxedDemoData(
        master_team_id=master_team_id,
        django_db_blocker=blocker,
        agent_model=agent_model,
        agent_runtime=agent_runtime,
        reasoning_effort=reasoning_effort,
        sandbox_timeout_seconds=sandbox_timeout_seconds,
    )
