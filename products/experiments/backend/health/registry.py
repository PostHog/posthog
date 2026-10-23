from collections.abc import Callable, Sequence
from typing import assert_never

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.experiments.backend.facade.contracts import (
    ExperimentHealth,
    ExperimentHealthCheckKey,
    ExperimentHealthCheckResult,
    ExperimentHealthCheckStatus,
    ExperimentHealthFinding,
)
from products.experiments.backend.health.checks.bias_risk import bias_risk_multiple_excluded
from products.experiments.backend.health.checks.bucketing_changed import bucketing_changed_mid_run
from products.experiments.backend.health.checks.conditions_changed import release_conditions_changed_mid_run
from products.experiments.backend.health.checks.early_significance import early_significance
from products.experiments.backend.health.checks.exposure_criteria import exposure_criteria_cannot_match
from products.experiments.backend.health.checks.flag_change_findings import flag_history_not_readable
from products.experiments.backend.health.checks.flag_state import flag_state
from products.experiments.backend.health.checks.flag_variants import flag_variants_mismatch
from products.experiments.backend.health.checks.forced_variant import forced_variant_release_condition
from products.experiments.backend.health.checks.metric_event_not_ingested import metric_event_not_ingested
from products.experiments.backend.health.checks.multiple_variants import multiple_variants_share
from products.experiments.backend.health.checks.new_flag_no_traffic import new_flag_no_traffic
from products.experiments.backend.health.checks.no_metric import no_metric
from products.experiments.backend.health.checks.split_changed import split_changed_mid_run
from products.experiments.backend.health.checks.srm import srm
from products.experiments.backend.health.checks.zero_exposures import zero_exposures
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import CheckOutcome, CheckSkip


@frozen
class HealthCheck:
    key: ExperimentHealthCheckKey
    name: str
    run: Callable[[HealthContext], CheckOutcome]


EXPERIMENT_HEALTH_CHECKS: tuple[HealthCheck, ...] = (
    HealthCheck(
        key=ExperimentHealthCheckKey.FLAG_STATE,
        name="Feature flag rollout",
        run=flag_state,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.FLAG_HISTORY,
        name="Feature flag history",
        run=flag_history_not_readable,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.SPLIT_CHANGED_MID_RUN,
        name="Variant split changes since launch",
        run=split_changed_mid_run,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.BUCKETING_CHANGED_MID_RUN,
        name="Flag key and bucketing changes since launch",
        run=bucketing_changed_mid_run,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.RELEASE_CONDITIONS_CHANGED_MID_RUN,
        name="Release condition changes since launch",
        run=release_conditions_changed_mid_run,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.FLAG_VARIANTS_MISMATCH,
        name="Feature flag variants",
        run=flag_variants_mismatch,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.FORCED_VARIANT_RELEASE_CONDITION,
        name="Release conditions that force a variant",
        run=forced_variant_release_condition,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.NEW_FLAG_NO_TRAFFIC,
        name="Feature flag traffic",
        run=new_flag_no_traffic,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.NO_METRIC,
        name="Metrics",
        run=no_metric,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.METRIC_EVENT_NOT_INGESTED,
        name="Metric events",
        run=metric_event_not_ingested,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.EXPOSURE_CRITERIA_CANNOT_MATCH,
        name="Exposure criteria",
        run=exposure_criteria_cannot_match,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.EARLY_SIGNIFICANCE,
        name="Sample size behind significant results",
        run=early_significance,
    ),
)

# The exposure query runs these on its answer. They must not include the checks above: the exposure answer
# is cached for a day, and a flag edit would not clear their findings.
EXPOSURE_HEALTH_CHECKS: tuple[HealthCheck, ...] = (
    HealthCheck(
        key=ExperimentHealthCheckKey.ZERO_EXPOSURES,
        name="Exposures",
        run=zero_exposures,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.SRM,
        name="Split of users across variants",
        run=srm,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.BIAS_RISK_MULTIPLE_EXCLUDED,
        name="Bias from an uneven split",
        run=bias_risk_multiple_excluded,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.MULTIPLE_VARIANTS_SHARE,
        name="Users exposed to multiple variants",
        run=multiple_variants_share,
    ),
)


_CHECK_FAILED = "Couldn't check because the check failed"


def evaluate(ctx: HealthContext, checks: Sequence[HealthCheck]) -> ExperimentHealth:
    findings: list[ExperimentHealthFinding] = []
    results: list[ExperimentHealthCheckResult] = []
    for check in checks:
        try:
            outcome = check.run(ctx)
        except Exception as error:
            # The findings ride on the health action, the exposure answer and `experiment launched`, so one
            # failing check must not fail them or hide the findings of the other checks.
            capture_exception(error)
            results.append(_result(check, ExperimentHealthCheckStatus.NOT_CHECKED, _CHECK_FAILED))
            continue
        match outcome:
            case CheckSkip(status=status, reason=reason):
                results.append(_result(check, status, reason))
            case ExperimentHealthFinding():
                findings.append(outcome)
                results.append(_result(check, ExperimentHealthCheckStatus.FINDING, None))
            case None:
                results.append(_result(check, ExperimentHealthCheckStatus.PASSED, None))
            case _:
                assert_never(outcome)
    return ExperimentHealth(findings=tuple(findings), checks=tuple(results))


def _result(check: HealthCheck, status: ExperimentHealthCheckStatus, reason: str | None) -> ExperimentHealthCheckResult:
    return ExperimentHealthCheckResult(key=check.key, name=check.name, status=status, reason=reason)
