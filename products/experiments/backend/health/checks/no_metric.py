from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.context import HealthContext


def no_metric(ctx: HealthContext) -> ExperimentHealthFinding | None:
    # The deprecated `filters` metric does not count, because no engine reads it.
    if not ctx.is_launched or ctx.primary_metric_count + ctx.secondary_metric_count > 0:
        return None
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.NO_METRIC,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="No metrics defined",
        detail=(
            "The experiment has launched, but it has no metric, so it shows no results. "
            "Add at least one metric. Metrics can be added, removed, or changed at any time."
        ),
        evidence={},
        actions=(
            ExperimentHealthFindingActionKind.ADD_PRIMARY_METRIC,
            ExperimentHealthFindingActionKind.ADD_SECONDARY_METRIC,
        ),
        diagnostic_ref=None,
    )
