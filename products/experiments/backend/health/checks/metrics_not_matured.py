"""
Primary metrics that can't have users yet, because the experiment is younger than their windows. Pure functions, no I/O.

With "Require completed conversion or retention window" on, the query of a metric leaves a user out until the metric's
window has passed. The exposure query applies no such filter, so the exposure count and `zero_exposures` look healthy
while the results show no users.
"""

from datetime import UTC

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.context import HealthContext, MetricWindow
from products.experiments.backend.health.skips import (
    NEEDS_PRIMARY_METRIC,
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    not_applicable,
    not_checked,
)
from products.experiments.backend.health.split_changes import format_change_time

_SETTING_LABEL = '"Require completed conversion or retention window"'
_SECONDS_PER_HOUR = 3600


def metrics_not_matured(ctx: HealthContext) -> CheckOutcome:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    if not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    if not ctx.only_count_matured_users:
        return not_applicable(f"Runs when {_SETTING_LABEL} is on")
    if ctx.primary_metric_count == 0:
        return not_applicable(NEEDS_PRIMARY_METRIC)
    windows = ctx.primary_metric_windows
    # The calculation leaves out a metric in the legacy format, which `primary_metric_count` counts.
    if windows == ():
        return not_applicable("Runs once the experiment has a primary metric in the current format")
    hours_since_launch = ctx.hours_since_launch
    if windows is None or hours_since_launch is None:
        return not_checked("Couldn't check because the primary metric windows couldn't be read")
    if not all(_holds_back_every_user(window, hours_since_launch) for window in windows):
        return None
    first_users = " and ".join(
        f'for "{window.name}" on {format_change_time(window.first_users_count_at, ctx.team_timezone)}'
        for window in windows
    )
    earliest = min(window.first_users_count_at for window in windows)
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.METRICS_NOT_MATURED,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.INFO,
        title="No users count yet because the metric windows aren't complete",
        detail=" ".join(
            [
                "A user counts for a metric only after the metric's conversion or retention window has passed, so no "
                "primary metric has users yet.",
                f"The first users can count {first_users}.",
                f"To count users sooner, turn off {_SETTING_LABEL} in the experiment's Settings tab.",
                "Users whose window is still open then count too.",
            ]
        ),
        evidence={
            "hours_since_launch": int(hours_since_launch),
            "first_users_count_at": earliest.astimezone(UTC).isoformat(),
        },
        actions=(),
        diagnostic_ref=None,
    )


def _holds_back_every_user(window: MetricWindow, hours_since_launch: float) -> bool:
    # `MaturityGate` counts a user at `anchor + window <= now`, so a user exposed at launch counts at the exact age of
    # the window.
    return window.window_seconds > 0 and hours_since_launch * _SECONDS_PER_HOUR < window.window_seconds
