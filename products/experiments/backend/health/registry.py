from collections.abc import Callable
from enum import StrEnum

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.experiments.backend.facade.contracts import ExperimentHealthFinding
from products.experiments.backend.health.checks.bias_risk import bias_risk_multiple_excluded
from products.experiments.backend.health.context import HealthContext


class HealthInput(StrEnum):
    CONFIG = "config"
    EXPOSURES = "exposures"


@frozen
class HealthCheck:
    inputs: frozenset[HealthInput]
    run: Callable[[HealthContext], ExperimentHealthFinding | None]


HEALTH_CHECKS: tuple[HealthCheck, ...] = (
    HealthCheck(inputs=frozenset({HealthInput.CONFIG, HealthInput.EXPOSURES}), run=bias_risk_multiple_excluded),
)


def evaluate(ctx: HealthContext) -> list[ExperimentHealthFinding]:
    """Runs every registered check whose inputs the context carries."""
    available = _available_inputs(ctx)
    findings: list[ExperimentHealthFinding] = []
    for check in HEALTH_CHECKS:
        if not check.inputs <= available:
            continue
        try:
            finding = check.run(ctx)
        except Exception as error:
            # The findings ride on responses such as the experiment detail, so one failing check
            # must not fail the response or hide the findings of the other checks.
            capture_exception(error)
            continue
        if finding is not None:
            findings.append(finding)
    return findings


def _available_inputs(ctx: HealthContext) -> frozenset[HealthInput]:
    if ctx.exposures is None:
        return frozenset({HealthInput.CONFIG})
    return frozenset({HealthInput.CONFIG, HealthInput.EXPOSURES})
