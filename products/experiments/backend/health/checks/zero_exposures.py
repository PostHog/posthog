from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.context import HealthContext

# A new experiment often has no exposure in its first hours, so the finding waits as long as the experiments scout does.
ZERO_EXPOSURES_GRACE_HOURS = 24


def zero_exposures(ctx: HealthContext) -> ExperimentHealthFinding | None:
    exposures = ctx.exposures
    if exposures is None or exposures.hours_since_launch is None or not ctx.is_launched:
        return None
    if exposures.hours_since_launch < ZERO_EXPOSURES_GRACE_HOURS or sum(exposures.total_exposures.values()) > 0:
        return None
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.ZERO_EXPOSURES,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="No users exposed",
        detail=(
            "No users have been exposed to this experiment, so it shows no results. "
            "Users are counted when the exposure event is sent for them. Check that your code evaluates "
            "the linked feature flag and that the exposure criteria match the events you send."
        ),
        evidence={"hours_since_launch": int(exposures.hours_since_launch)},
        actions=(ExperimentHealthFindingActionKind.EDIT_EXPOSURE_CRITERIA,),
        diagnostic_ref=None,
    )
