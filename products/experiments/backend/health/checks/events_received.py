"""What the checks of events the project never received share. Pure functions, no I/O.

Ingestion sets `last_seen_at` on an event definition when it sees the event in the project, so a name without a seen
definition was never received. Wizard writes definitions without it for the events it plans. Before launch that is
normal: the code that sends the event often ships with the launch.
"""

from collections.abc import Sequence

from products.experiments.backend.facade.contracts import ExperimentHealthFindingSeverity
from products.experiments.backend.health.checks.zero_exposures import ZERO_EXPOSURES_GRACE_HOURS
from products.experiments.backend.health.context import HealthContext


def not_received_severity(ctx: HealthContext, *, affects_results: bool) -> ExperimentHealthFindingSeverity:
    hours = ctx.hours_since_launch
    if affects_results and ctx.is_launched and hours is not None and hours >= ZERO_EXPOSURES_GRACE_HOURS:
        return ExperimentHealthFindingSeverity.WARNING
    return ExperimentHealthFindingSeverity.INFO


def joined(items: Sequence[str], conjunction: str = "and") -> str:
    if len(items) < 3:
        return f" {conjunction} ".join(items)
    return f"{', '.join(items[:-1])}, {conjunction} {items[-1]}"


def quoted(names: Sequence[str], conjunction: str = "and") -> str:
    return joined([f'"{name}"' for name in names], conjunction)
