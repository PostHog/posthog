from collections.abc import Callable

from posthog.exceptions_capture import capture_exception

from products.experiments.backend.facade.contracts import ExperimentHealthFinding
from products.experiments.backend.health.checks.bias_risk import bias_risk_multiple_excluded
from products.experiments.backend.health.checks.flag_state import flag_state
from products.experiments.backend.health.checks.no_metric import no_metric
from products.experiments.backend.health.context import HealthContext

HealthCheck = Callable[[HealthContext], ExperimentHealthFinding | None]

HEALTH_CHECKS: tuple[HealthCheck, ...] = (flag_state, no_metric, bias_risk_multiple_excluded)


def evaluate(ctx: HealthContext) -> list[ExperimentHealthFinding]:
    """Runs every registered check. A check returns None when the context lacks an input it reads."""
    findings: list[ExperimentHealthFinding] = []
    for check in HEALTH_CHECKS:
        try:
            finding = check(ctx)
        except Exception as error:
            # The findings ride on responses such as the experiment detail, so one failing check
            # must not fail the response or hide the findings of the other checks.
            capture_exception(error)
            continue
        if finding is not None:
            findings.append(finding)
    return findings
