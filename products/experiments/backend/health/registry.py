from collections.abc import Callable, Sequence

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.experiments.backend.facade.contracts import (
    ExperimentHealth,
    ExperimentHealthCheckKey,
    ExperimentHealthCheckResult,
    ExperimentHealthCheckStatus,
    ExperimentHealthFinding,
)
from products.experiments.backend.health.checks.bias_risk import bias_risk_multiple_excluded, bias_risk_skip
from products.experiments.backend.health.checks.bucketing_changed import bucketing_changed_mid_run
from products.experiments.backend.health.checks.conditions_changed import release_conditions_changed_mid_run
from products.experiments.backend.health.checks.exposure_criteria import (
    exposure_criteria_cannot_match,
    exposure_criteria_skip,
)
from products.experiments.backend.health.checks.flag_change_findings import (
    flag_change_skip,
    flag_history_not_readable,
    flag_history_skip,
)
from products.experiments.backend.health.checks.flag_state import flag_state, flag_state_skip
from products.experiments.backend.health.checks.flag_variants import flag_variants_mismatch, flag_variants_skip
from products.experiments.backend.health.checks.forced_variant import (
    forced_variant_release_condition,
    forced_variant_skip,
)
from products.experiments.backend.health.checks.metric_event_not_ingested import (
    metric_event_not_ingested,
    metric_event_not_ingested_skip,
)
from products.experiments.backend.health.checks.multiple_variants import (
    multiple_variants_share,
    multiple_variants_share_skip,
)
from products.experiments.backend.health.checks.new_flag_no_traffic import new_flag_no_traffic, new_flag_no_traffic_skip
from products.experiments.backend.health.checks.no_metric import no_metric, no_metric_skip
from products.experiments.backend.health.checks.split_changed import split_changed_mid_run
from products.experiments.backend.health.checks.srm import srm, srm_skip
from products.experiments.backend.health.checks.zero_exposures import zero_exposures, zero_exposures_skip
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import CheckSkip


@frozen
class HealthCheck:
    key: ExperimentHealthCheckKey
    name: str
    # Returns None when it finds no problem, and also when the context lacks an input it reads.
    find: Callable[[HealthContext], ExperimentHealthFinding | None]
    # Why the check does not look, or None when it looks. Keep in step with the guards of `find`.
    skip: Callable[[HealthContext], CheckSkip | None]


EXPERIMENT_HEALTH_CHECKS: tuple[HealthCheck, ...] = (
    HealthCheck(
        key=ExperimentHealthCheckKey.FLAG_STATE,
        name="Feature flag rollout",
        find=flag_state,
        skip=flag_state_skip,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.FLAG_HISTORY,
        name="Feature flag history",
        find=flag_history_not_readable,
        skip=flag_history_skip,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.SPLIT_CHANGED_MID_RUN,
        name="Variant split changes since launch",
        find=split_changed_mid_run,
        skip=flag_change_skip,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.BUCKETING_CHANGED_MID_RUN,
        name="Flag key and bucketing changes since launch",
        find=bucketing_changed_mid_run,
        skip=flag_change_skip,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.RELEASE_CONDITIONS_CHANGED_MID_RUN,
        name="Release condition changes since launch",
        find=release_conditions_changed_mid_run,
        skip=flag_change_skip,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.FLAG_VARIANTS_MISMATCH,
        name="Feature flag variants",
        find=flag_variants_mismatch,
        skip=flag_variants_skip,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.FORCED_VARIANT_RELEASE_CONDITION,
        name="Release conditions that force a variant",
        find=forced_variant_release_condition,
        skip=forced_variant_skip,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.NEW_FLAG_NO_TRAFFIC,
        name="Feature flag traffic",
        find=new_flag_no_traffic,
        skip=new_flag_no_traffic_skip,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.NO_METRIC,
        name="Metrics",
        find=no_metric,
        skip=no_metric_skip,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.METRIC_EVENT_NOT_INGESTED,
        name="Metric events",
        find=metric_event_not_ingested,
        skip=metric_event_not_ingested_skip,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.EXPOSURE_CRITERIA_CANNOT_MATCH,
        name="Exposure criteria",
        find=exposure_criteria_cannot_match,
        skip=exposure_criteria_skip,
    ),
)

# The exposure query runs these on its answer. They must not include the checks above: the exposure answer
# is cached for a day, and a flag edit would not clear their findings.
EXPOSURE_HEALTH_CHECKS: tuple[HealthCheck, ...] = (
    HealthCheck(
        key=ExperimentHealthCheckKey.ZERO_EXPOSURES,
        name="Exposures",
        find=zero_exposures,
        skip=zero_exposures_skip,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.SRM,
        name="Split of users across variants",
        find=srm,
        skip=srm_skip,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.BIAS_RISK_MULTIPLE_EXCLUDED,
        name="Bias from an uneven split",
        find=bias_risk_multiple_excluded,
        skip=bias_risk_skip,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.MULTIPLE_VARIANTS_SHARE,
        name="Users exposed to multiple variants",
        find=multiple_variants_share,
        skip=multiple_variants_share_skip,
    ),
)


_CHECK_FAILED = "Couldn't check because the check failed"


def evaluate(ctx: HealthContext, checks: Sequence[HealthCheck]) -> ExperimentHealth:
    findings: list[ExperimentHealthFinding] = []
    results: list[ExperimentHealthCheckResult] = []
    for check in checks:
        try:
            # Every check runs whatever its skip says, so a skip that is out of step with the check's guards can't
            # hide a finding. The skip is read only without a finding, so a failing skip can't hide one either.
            finding = check.find(ctx)
            skip = check.skip(ctx) if finding is None else None
        except Exception as error:
            # The findings ride on the health action, the exposure answer and `experiment launched`, so one
            # failing check must not fail them or hide the findings of the other checks.
            capture_exception(error)
            results.append(_result(check, ExperimentHealthCheckStatus.NOT_CHECKED, _CHECK_FAILED))
            continue
        if finding is not None:
            findings.append(finding)
            results.append(_result(check, ExperimentHealthCheckStatus.FINDING, None))
        elif skip is not None:
            results.append(_result(check, skip.status, skip.reason))
        else:
            results.append(_result(check, ExperimentHealthCheckStatus.PASSED, None))
    return ExperimentHealth(findings=tuple(findings), checks=tuple(results))


def _result(check: HealthCheck, status: ExperimentHealthCheckStatus, reason: str | None) -> ExperimentHealthCheckResult:
    return ExperimentHealthCheckResult(key=check.key, name=check.name, status=status, reason=reason)
