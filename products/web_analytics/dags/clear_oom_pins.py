"""Operator job to list or clear web-analytics precompute OOM pins.

A pinned team's precompute inserts are capped to 1-day windows (set reactively after a
MEMORY_LIMIT_EXCEEDED insert, self-expiring in 14 days). Clear a pin when the underlying
pressure is gone, e.g. after a cluster upscale or a stored-row cap reduction, so the
team's inserts run at full band width again.

Run manually from the Dagster UI. With no run config it only lists the pinned teams (dry
run); clearing requires explicitly setting `team_id` or `clear_all: true`, which is the
confirmation step — every pin exists because that team recently OOMed a full-width
insert, so a global clear re-exposes all of them at once.
"""

import dagster

from posthog.dags.common import JobOwners

from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    clear_team_oom_pin,
    list_oom_pinned_team_ids,
)


class ClearOomPinsConfig(dagster.Config):
    team_id: int | None = None
    clear_all: bool = False


@dagster.op
def clear_precompute_oom_pins_op(context: dagster.OpExecutionContext, config: ClearOomPinsConfig) -> None:
    if config.team_id is not None and config.clear_all:
        raise dagster.Failure("Pass team_id or clear_all, not both.")

    pinned = list_oom_pinned_team_ids()
    context.log.info(f"OOM-pinned teams: {pinned or 'none'}")

    if config.team_id is not None:
        if clear_team_oom_pin(config.team_id):
            context.log.info(f"Cleared OOM pin for team {config.team_id}")
        else:
            context.log.info(f"Team {config.team_id} was not pinned; nothing to clear")
        return

    if config.clear_all:
        for team_id in pinned:
            clear_team_oom_pin(team_id)
        context.log.info(f"Cleared {len(pinned)} OOM pin(s)")
        return

    context.log.info("Dry run: no team_id or clear_all in run config, nothing cleared")


@dagster.job(
    name="web_analytics_clear_precompute_oom_pins",
    description=(
        "List or clear web-analytics precompute OOM pins. Without run config this is a "
        "dry run that lists pinned teams; set `team_id` to clear one pin or "
        "`clear_all: true` to clear every pin."
    ),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_clear_precompute_oom_pins_job() -> None:
    clear_precompute_oom_pins_op()
