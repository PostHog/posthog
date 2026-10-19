from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TypedDict

from products.experiments.backend.facade.contracts import ExperimentHealthFlagChangeKind
from products.experiments.backend.health.context import (
    FlagChange,
    FlagHistory,
    FlagHistoryNotChecked,
    FlagHistoryNotCheckedReason,
    HealthContext,
)

# Tests set what their check reads with `dataclasses.replace`, so a new field of the context changes only this file.
RUNNING_CONTEXT = HealthContext(
    is_launched=True,
    is_running=True,
    has_ended=False,
    is_paused=False,
    archived=False,
    flag=None,
    baseline_variant_key=None,
    primary_metric_count=1,
    secondary_metric_count=0,
    exposures=None,
    flag_history=None,
    condition_set_traffic=None,
    excluded_variant_keys=frozenset(),
)


class Status(TypedDict):
    is_launched: bool
    is_running: bool
    has_ended: bool


RUNNING: Status = {"is_launched": True, "is_running": True, "has_ended": False}
ENDED: Status = {"is_launched": True, "is_running": False, "has_ended": True}
DRAFT: Status = {"is_launched": False, "is_running": False, "has_ended": False}


def flag_history(
    changes: Sequence[FlagChange],
    *,
    launched_at: datetime,
    exposed_before_first: bool | None = True,
    exposed_between: Mapping[ExperimentHealthFlagChangeKind, bool | None] | None = None,
    not_checked: FlagHistoryNotCheckedReason | None = None,
) -> FlagHistory | FlagHistoryNotChecked:
    # Every change counts from the first, as when someone was exposed before it.
    if not_checked is not None:
        return FlagHistoryNotChecked(
            reason=not_checked, launched_at=launched_at, team_timezone="Europe/Berlin", changes=tuple(changes)
        )
    return FlagHistory(
        launched_at=launched_at,
        team_timezone="Europe/Berlin",
        changes=tuple(changes),
        counted_since=changes[0].changed_at if changes else None,
        exposed_before_first=exposed_before_first,
        exposed_between=exposed_between or {},
    )
