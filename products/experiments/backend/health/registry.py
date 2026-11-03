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
    ExperimentHealthMeasurement,
)
from products.experiments.backend.health.checks.bias_risk import bias_risk_multiple_excluded
from products.experiments.backend.health.checks.bucketing_changed import bucketing_changed_mid_run
from products.experiments.backend.health.checks.conditions_changed import release_conditions_changed_mid_run
from products.experiments.backend.health.checks.early_significance import early_significance
from products.experiments.backend.health.checks.exposure_criteria import exposure_criteria_cannot_match
from products.experiments.backend.health.checks.exposure_filters import exposure_filters
from products.experiments.backend.health.checks.filtered_exposures import exposures_removed_by_test_account_filter
from products.experiments.backend.health.checks.flag_change_findings import flag_history_not_readable
from products.experiments.backend.health.checks.flag_state import flag_state
from products.experiments.backend.health.checks.flag_variants import flag_variants_mismatch
from products.experiments.backend.health.checks.forced_variant import forced_variant_release_condition
from products.experiments.backend.health.checks.metric_all_zero import metric_all_zero
from products.experiments.backend.health.checks.metric_calculation_failed import metric_calculation_failed
from products.experiments.backend.health.checks.metric_cannot_compile import metric_cannot_compile
from products.experiments.backend.health.checks.metric_event_not_ingested import metric_event_not_ingested
from products.experiments.backend.health.checks.metrics_not_matured import metrics_not_matured
from products.experiments.backend.health.checks.multiple_variants import multiple_variants_share
from products.experiments.backend.health.checks.new_flag_no_traffic import new_flag_no_traffic
from products.experiments.backend.health.checks.no_metric import no_metric
from products.experiments.backend.health.checks.shared_flag import flag_shared
from products.experiments.backend.health.checks.split_changed import split_changed_mid_run
from products.experiments.backend.health.checks.srm import srm
from products.experiments.backend.health.checks.zero_exposures import zero_exposures
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import CheckOutcome, CheckPassed, CheckSkip


@frozen
class HealthCheck:
    key: ExperimentHealthCheckKey
    name: str
    # What the check looks for and why it matters. The tab shows it for every status, so it holds for every experiment.
    description: str
    run: Callable[[HealthContext], CheckOutcome]


EXPERIMENT_HEALTH_CHECKS: tuple[HealthCheck, ...] = (
    HealthCheck(
        key=ExperimentHealthCheckKey.FLAG_STATE,
        name="Flag state that doesn't match the experiment",
        description=(
            "Checks that the feature flag matches the experiment's status. A running experiment needs a flag that is "
            "on and serves every variant, or new users stop entering it. Before launch and after the end, a flag that "
            "serves variants shows them to users that the results don't count."
        ),
        run=flag_state,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.FLAG_SHARED,
        name="Other experiments on the same flag",
        run=flag_shared,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.FLAG_HISTORY,
        name="Unreadable flag history",
        description=(
            "Reads the feature flag's history since launch. The checks of changes since launch need it, so without it "
            "they can't tell whether a change affected the results."
        ),
        run=flag_history_not_readable,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.SPLIT_CHANGED_MID_RUN,
        name="Variant split changes since launch",
        description=(
            "Looks for changes to the variant split after users were first exposed. A change can move users who "
            "already saw one variant to another, which mixes their behavior across variants and biases the results."
        ),
        run=split_changed_mid_run,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.BUCKETING_CHANGED_MID_RUN,
        name="Variant assignment changes since launch",
        description=(
            'Looks for changes after launch to how the flag assigns variants, such as its key or "Match by". Users who '
            "were already exposed can then get a new variant, which mixes their behavior across variants and biases "
            "the results."
        ),
        run=bucketing_changed_mid_run,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.RELEASE_CONDITIONS_CHANGED_MID_RUN,
        name="Release condition changes since launch",
        description=(
            "Looks for release condition changes after users were first exposed. A change can let in other users or "
            "move users to another variant, so the results mix two different setups."
        ),
        run=release_conditions_changed_mid_run,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.FLAG_VARIANTS_MISMATCH,
        name="Flag variants not set up",
        description=(
            "Checks that the feature flag has the experiment's variants, including the baseline. Without them, PostHog "
            "can't assign users to the variants or compare the variants with the baseline."
        ),
        run=flag_variants_mismatch,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.FORCED_VARIANT_RELEASE_CONDITION,
        name="Release conditions that force a variant",
        description=(
            "Looks for release conditions that give users a fixed variant instead of a random one. The comparison is "
            "fair only for randomly assigned users, so a large override can bias the results."
        ),
        run=forced_variant_release_condition,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.NEW_FLAG_NO_TRAFFIC,
        name="Flag calls not received yet",
        description=(
            "Checks before launch that PostHog receives calls to the feature flag. The experiment counts users only "
            "after your code evaluates the flag, so a launch before then starts the running time without users."
        ),
        run=new_flag_no_traffic,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.NO_METRIC,
        name="Metrics not set up",
        description=(
            "Checks that a launched experiment has at least one metric. Without a metric, the experiment counts "
            "exposures but has nothing to compare the variants on."
        ),
        run=no_metric,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.METRIC_EVENT_NOT_INGESTED,
        name="Metric events not received yet",
        description=(
            "Checks that the project receives the events that each metric uses. A metric whose event never arrives "
            "stays at zero, so it can't show a difference between the variants."
        ),
        run=metric_event_not_ingested,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.METRIC_CANNOT_COMPILE,
        name="Invalid metric definitions",
        description=(
            "Builds the query of each metric without running it, to find definitions that can't be calculated. Such a "
            "metric shows no results until you fix it."
        ),
        run=metric_cannot_compile,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.METRIC_CALCULATION_FAILED,
        name="Failed metric calculations",
        description=(
            "Reads the latest calculation of each metric and reports the ones that failed. A failed metric shows old "
            "results or none, and some failures repeat until you change the metric or a setting."
        ),
        run=metric_calculation_failed,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.METRIC_ALL_ZERO,
        name="Metrics at zero in every variant",
        description=(
            "Looks for metrics that stay at zero in every variant after enough users and time. This usually means that "
            "the metric events have a different ID than the exposures, so the metric can't show a difference."
        ),
        run=metric_all_zero,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.EXPOSURE_CRITERIA_CANNOT_MATCH,
        name="Exposure criteria that can't match",
        description=(
            "Checks that events can match the exposure criteria, for example that the project receives the custom "
            "exposure event. Criteria that no event matches leave the experiment without exposed users."
        ),
        run=exposure_criteria_cannot_match,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.EXPOSURE_FILTERS,
        name="Dynamic cohorts in the exposure criteria",
        description=(
            "Looks for dynamic cohorts in the exposure criteria. The results read a dynamic cohort's members at the "
            "time of the calculation, not at each user's exposure, so users who join or leave during the run can bias "
            "the results."
        ),
        run=exposure_filters,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.EARLY_SIGNIFICANCE,
        name="Significance on a small sample",
        description=(
            "Compares a significant result with the smallest difference that the sample can reliably detect. A "
            "significant result on a small sample often shrinks or goes away as more users arrive, so a decision on it "
            "can ship the wrong variant."
        ),
        run=early_significance,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.METRICS_NOT_MATURED,
        name="Metric windows not complete yet",
        description=(
            "Checks whether the primary metrics have results yet when the experiment waits for complete conversion or "
            "retention windows. A user counts only after their window passes, so a new experiment can show no results "
            "while nothing is wrong."
        ),
        run=metrics_not_matured,
    ),
)

# The exposure query runs these on its answer. They must not include the checks above: the exposure answer
# is cached for a day, and a flag edit would not clear their findings. `srm` reads the verdict of
# `split_changed_mid_run`, which only a split edit can change, and the variant overrides of the release conditions. The
# split and the release conditions are part of the exposure query's cache key.
EXPOSURE_HEALTH_CHECKS: tuple[HealthCheck, ...] = (
    HealthCheck(
        key=ExperimentHealthCheckKey.ZERO_EXPOSURES,
        name="Exposures not received since launch",
        description=(
            "Checks that users are exposed after launch. An experiment without exposures has no results, which usually "
            "means that your code doesn't evaluate the flag or that no event matches the exposure criteria."
        ),
        run=zero_exposures,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.TEST_ACCOUNT_FILTER_REMOVES_EXPOSURES,
        name="Test account filters that leave out most users",
        description=(
            "Compares the exposed users with and without the test account filters. Filters that leave out most users "
            "often match real users by mistake, so the results measure only a small part of your users."
        ),
        run=exposures_removed_by_test_account_filter,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.SRM,
        name="Split of users across variants",
        description=(
            "Tests whether exposed users are divided across variants in the percentages of the variant split. A "
            "mismatch usually means that a variant override, the assignment or the tracking adds or loses users in "
            "one variant, which can bias the results."
        ),
        run=srm,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.BIAS_RISK_MULTIPLE_EXCLUDED,
        name="Bias from an uneven split",
        description=(
            "Looks for users exposed to multiple variants when the variant split is uneven. The results leave these "
            "users out, and the smaller variant loses a larger share of its users, which biases the comparison."
        ),
        run=bias_risk_multiple_excluded,
    ),
    HealthCheck(
        key=ExperimentHealthCheckKey.MULTIPLE_VARIANTS_SHARE,
        name="Users exposed to multiple variants",
        description=(
            "Counts the users exposed to more than one variant, which the results leave out. A high share usually "
            "means that one person has several IDs, and the variants can then lose different users, which biases the "
            "results."
        ),
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
            case CheckPassed(measurement=measurement):
                results.append(_result(check, ExperimentHealthCheckStatus.PASSED, None, measurement))
            case None:
                results.append(_result(check, ExperimentHealthCheckStatus.PASSED, None))
            case _:
                assert_never(outcome)
    return ExperimentHealth(findings=tuple(findings), checks=tuple(results))


def _result(
    check: HealthCheck,
    status: ExperimentHealthCheckStatus,
    reason: str | None,
    measurement: ExperimentHealthMeasurement | None = None,
) -> ExperimentHealthCheckResult:
    return ExperimentHealthCheckResult(
        key=check.key,
        name=check.name,
        description=check.description,
        status=status,
        reason=reason,
        measurement=measurement,
    )
