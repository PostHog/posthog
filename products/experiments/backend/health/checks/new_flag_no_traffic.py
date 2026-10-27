"""
A draft whose feature flag has no recorded call. Pure functions, no I/O.

The experiment's users get their variants from the flag, so a launch before the flag gets traffic starts the run with
nobody in it. The finding names the missing traffic, not missing code: a flag can be evaluated in code that has no
users yet, or through a call that records nothing.
"""

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.delays import LAST_CALLED_AT_LAG
from products.experiments.backend.health.skips import (
    FLAG_DELETED,
    NO_FLAG,
    NOT_ON_ARCHIVED,
    RUNS_BEFORE_LAUNCH,
    CheckOutcome,
    not_applicable,
    not_checked,
)


def new_flag_no_traffic(ctx: HealthContext) -> CheckOutcome:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    # After launch, the zero exposures check reports an experiment without traffic.
    if ctx.is_launched:
        return not_applicable(RUNS_BEFORE_LAUNCH)
    if ctx.flag is None:
        return not_applicable(NO_FLAG)
    if ctx.flag.deleted:
        return not_applicable(FLAG_DELETED)
    if ctx.flag_called is None:
        return not_checked(
            "Couldn't check because this organization's flag calls are stored where this check can't read them"
        )
    if ctx.flag_called:
        return None
    # Without an active flag the web SDK records no call, so the flag gets traffic only after the launch activates it,
    # and the finding's advice could not be followed.
    if ctx.team_has_active_flag is not True:
        return not_checked(
            "Couldn't check because PostHog's JavaScript SDK only requests flags once a flag in this project is enabled"
        )
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.NEW_FLAG_NO_TRAFFIC,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.INFO,
        title="The feature flag has no traffic yet",
        detail=(
            "PostHog hasn't recorded any calls to the linked feature flag yet. The experiment only counts users after "
            "your code evaluates the flag, so launch after the flag starts getting traffic. New calls can take up to "
            f"{LAST_CALLED_AT_LAG} to show up here."
        ),
        evidence={},
        actions=(),
        diagnostic_ref=None,
    )
