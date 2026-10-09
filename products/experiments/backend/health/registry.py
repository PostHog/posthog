from collections.abc import Callable, Sequence

from posthog.exceptions_capture import capture_exception

from products.experiments.backend.facade.contracts import ExperimentHealthFinding
from products.experiments.backend.health.checks.bias_risk import bias_risk_multiple_excluded
from products.experiments.backend.health.checks.flag_state import flag_state
from products.experiments.backend.health.checks.forced_variant import forced_variant_release_condition
from products.experiments.backend.health.checks.no_metric import no_metric
from products.experiments.backend.health.checks.srm import srm
from products.experiments.backend.health.checks.zero_exposures import zero_exposures
from products.experiments.backend.health.context import HealthContext

HealthCheck = Callable[[HealthContext], ExperimentHealthFinding | None]

EXPERIMENT_HEALTH_CHECKS: tuple[HealthCheck, ...] = (flag_state, forced_variant_release_condition, no_metric)

# The exposure query runs these on its answer. They must not include the checks above: the exposure answer
# is cached for a day, and a flag edit would not clear their findings.
EXPOSURE_HEALTH_CHECKS: tuple[HealthCheck, ...] = (zero_exposures, srm, bias_risk_multiple_excluded)


def evaluate(ctx: HealthContext, checks: Sequence[HealthCheck]) -> list[ExperimentHealthFinding]:
    """Runs the given checks. A check returns None when the context lacks an input it reads."""
    findings: list[ExperimentHealthFinding] = []
    for check in checks:
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
