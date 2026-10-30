import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    BiasRisk,
    CachedExperimentExposureQueryResponse,
    DateRange,
    ExperimentExposureHealthCheck,
    ExperimentExposureHealthCheckKey,
    ExperimentExposureHealthCheckStatus,
    ExperimentExposureHealthFinding,
    ExperimentExposureHealthFindingActionKind,
    ExperimentExposureHealthFindingCode,
    ExperimentExposureHealthFindingSeverity,
    ExperimentExposureQuery,
    ExperimentExposureQueryResponse,
    ExperimentExposureTimeSeries,
    IntervalType,
    MultipleVariantHandling,
    SampleRatioMismatch,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, get_query_tags, tag_queries, tags_context
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.user import User

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.experiments.backend.facade.contracts import ExperimentHealth, ExperimentHealthReaderAccess
from products.experiments.backend.health.checks.bias_risk import evaluate_bias_risk
from products.experiments.backend.health.checks.srm import (
    TOP_SEGMENT_VALUES,
    reads_flag_history,
    reads_segments,
    sample_ratio_test,
    segments_first_exposed_after,
)
from products.experiments.backend.health.checks.zero_exposures import reads_exposed_without_test_account_filter
from products.experiments.backend.health.context import (
    ExposureSegment,
    ExposureTotals,
    FlagHistory,
    FlagHistoryNotChecked,
    load_health_context,
)
from products.experiments.backend.health.exposure_gate import load_split_history
from products.experiments.backend.health.registry import (
    EXPOSURE_HEALTH_CHECKS,
    evaluate as evaluate_health,
)
from products.experiments.backend.health.rollout import shows_health_findings
from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY
from products.experiments.backend.hogql_queries.base_query_utils import analysis_window, analysis_window_end
from products.experiments.backend.hogql_queries.error_handling import experiment_error_handler
from products.experiments.backend.hogql_queries.experiment_exposure_query_builder import ExposureSegmentDimension
from products.experiments.backend.hogql_queries.experiment_query_builder import (
    ExperimentQueryBuilder,
    ExposureQueryParams,
    get_exposure_config_params_for_builder,
)
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentResultsCacheMixin
from products.experiments.backend.hogql_queries.exposure_query_logic import aggregates_by_group, get_entity_key
from products.experiments.backend.hogql_queries.precompute_policy import (
    ensure_exposures_precomputed,
    team_precompute_skip_reason,
)
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

logger = structlog.get_logger(__name__)

QUERY_ROW_LIMIT = 5000  # The result has one row per (day, variant) pair
# The queries that explain a health finding scan the exposure events. A timeout keeps the finding without the
# explanation, so it must not hold up the exposure answer as long as its own query can.
HEALTH_QUERY_TIMEOUT_SECONDS = 60


def build_experiment_exposure_query(experiment: Experiment) -> ExperimentExposureQuery:
    """The exposure query of an experiment over its own window. Backend callers build it here, so callers with the same
    access to the flag's history share one cache entry. The page builds its own, with the whole flag, so it caches
    apart."""
    feature_flag = experiment.feature_flag
    # The FK gives a model instance, and the query field is a pydantic type with no
    # attribute-based validation, so it must be serialized first.
    experiment_holdout = experiment.holdout
    holdout = (
        {"id": experiment_holdout.id, "name": experiment_holdout.name, "filters": experiment_holdout.filters}
        if experiment_holdout is not None
        else None
    )
    return ExperimentExposureQuery(
        experiment_id=experiment.id,
        experiment_name=experiment.name,
        feature_flag={"key": feature_flag.key, "filters": feature_flag.filters},
        start_date=experiment.start_date.isoformat() if experiment.start_date else None,
        end_date=experiment.end_date.isoformat() if experiment.end_date else None,
        exposure_criteria=experiment.exposure_criteria,
        holdout=holdout,
    )


class ExperimentExposuresQueryRunner(ExperimentResultsCacheMixin, QueryRunner):
    query: ExperimentExposureQuery
    cached_response: CachedExperimentExposureQueryResponse

    def __init__(self, *args, error_event_context: str | None = "ui", **kwargs):
        super().__init__(*args, **kwargs)
        # Same contract as ExperimentQueryRunner.__init__: tags the terminal error event, and None keeps it silent.
        self.error_event_context = error_event_context
        # The user id and whether that user may read the flag's history.
        self._flag_history_access: tuple[int, bool] | None = None
        self._health_findings_shown: tuple[int, bool] | None = None

        if not self.query.experiment_id:
            raise ValidationError("experiment_id is required")

        feature_flag_key = self.query.feature_flag.get("key")
        if not isinstance(feature_flag_key, str) or not feature_flag_key:
            raise ValidationError("feature_flag key is required")
        self.exposure_criteria = self.query.exposure_criteria

        try:
            self.experiment = Experiment.objects.get(id=self.query.experiment_id, team=self.team)
        except Experiment.DoesNotExist:
            raise ValidationError(f"Experiment with id {self.query.experiment_id} not found")
        self.feature_flag_key: str = self.experiment.feature_flag.key_without_tombstone()
        # Read from the DB flag, not the query dict, because callers pass different feature_flag
        # shapes (full flag object or bare filters). A missed group index would bypass the
        # group-aggregation precompute gate below.
        self.group_type_index = (self.experiment.feature_flag.filters or {}).get("aggregation_group_type_index")

        # The analysis window comes from the query, not live model state. The result is cached under
        # a key hashed from self.query (see get_cache_payload), so the computed window must match the
        # window the query declares. Otherwise the key can describe a window the result was not
        # computed for. A running experiment serializes end_date=None, which expands to now() here.
        # The expansion does not change self.query, so the moving instant stays out of the cache key
        # and the cache TTL governs refresh.
        self.window_start = datetime.fromisoformat(self.query.start_date) if self.query.start_date else None
        self.window_end_date = datetime.fromisoformat(self.query.end_date) if self.query.end_date else None
        self.as_of = self.window_end_date or datetime.now(UTC)

        # Holdout is intentionally not appended: holdout users were never exposed to
        # the experiment, so they don't belong in the exposure chart. self.query.holdout
        # is still consulted by _calculate_srm for the holdout-adjusted rollout math.
        self.excluded_variants = set(self.experiment.excluded_variants or [])
        multivariate_data = (self.query.feature_flag.get("filters") or {}).get("multivariate") or {}
        self.variants = [
            variant.get("key")
            for variant in multivariate_data.get("variants", [])
            if variant.get("key") not in self.excluded_variants
        ]
        # No variants means the exposure SQL (`variant IN {variants}`) matches nothing. For a
        # running experiment that is a broken flag, so raise instead of rendering an empty chart
        # that reads as "no exposures". A stopped or draft experiment can legitimately keep a flag
        # that was later changed to boolean, so it falls through to an empty result.
        if not multivariate_data.get("variants") and self.experiment.is_running:
            raise ValidationError(
                "This experiment's feature flag has no variants. Restore the flag's variants to see exposure data."
            )

        self.date_range = self._get_date_range()
        self.date_range_query = QueryDateRange(
            date_range=self.date_range,
            team=self.team,
            interval=IntervalType.DAY,
            now=datetime.now(),
        )

    def _get_date_range(self) -> DateRange:
        return analysis_window(self.window_start, self.window_end_date, self.team, self.as_of)

    def _ensure_exposures_precomputed(self, builder: ExperimentQueryBuilder) -> LazyComputationResult:
        if not self.window_start:
            raise ValidationError("Experiment must have a start date for lazy computation")

        return ensure_exposures_precomputed(
            self.team,
            builder,
            self.window_start,
            analysis_window_end(self.window_end_date, self.as_of),
        )

    def _query_builder(self, exposure_params: ExposureQueryParams) -> ExperimentQueryBuilder:
        return ExperimentQueryBuilder(
            team=self.team,
            feature_flag_key=self.feature_flag_key,
            exposure_config=exposure_params.exposure_config,
            filter_test_accounts=exposure_params.filter_test_accounts,
            multiple_variant_handling=exposure_params.multiple_variant_handling,
            variants=self.variants,
            date_range_query=self.date_range_query,
            entity_key=get_entity_key(self.group_type_index),
            activation_config=exposure_params.activation_config,
        )

    def _get_exposure_query(self, exposure_params: ExposureQueryParams) -> ast.SelectQuery:
        builder = self._query_builder(exposure_params)

        # TODO: Add a query-level precomputation_mode override for ExperimentExposureQuery. The main
        # runner lets PrecomputationMode.PRECOMPUTED bypass the duration gate. This path has no such
        # override, so callers cannot force precomputation for an experiment below the minimum duration.
        # The group_type_index check mirrors the main runner: group builds always fail, because the
        # INSERT cannot resolve the materialized $group_N column on sharded_events.
        if (
            self.group_type_index is None
            and team_precompute_skip_reason(
                self.team,
                get_or_create_team_extension(self.team, TeamExperimentsConfig),
                self.experiment,
                self.exposure_criteria,
            )
            is None
        ):
            try:
                with tags_context(experiment_query_surface="precompute_build", experiment_precompute_table="exposures"):
                    result = self._ensure_exposures_precomputed(builder)
                if result.ready:
                    job_ids = [str(job_id) for job_id in result.job_ids]
                    tag_queries(experiment_exposures_path="precomputed")
                    return builder.get_daily_exposures_from_precomputed(job_ids)
                else:
                    logger.warning("exposure_lazy_computation_not_ready", experiment_id=self.experiment.id)
            except Exception:
                logger.exception("exposure_lazy_computation_failed", experiment_id=self.experiment.id)

        tag_queries(experiment_exposures_path="direct_scan")
        return builder.get_exposure_timeseries_query()

    def _calculate_srm(self, total_exposures: dict[str, int]) -> SampleRatioMismatch | None:
        """Chi-squared goodness-of-fit test of the observed variant counts against the rollout
        percentages. Returns None when there is too little data."""
        multivariate_data = (self.query.feature_flag.get("filters") or {}).get("multivariate") or {}
        variants_config = multivariate_data.get("variants", [])

        if not variants_config or not total_exposures:
            return None

        rollout_percentages: dict[str, float] = {}
        for variant_config in variants_config:
            key = variant_config.get("key")
            pct = variant_config.get("rollout_percentage", 0)
            if key:
                rollout_percentages[key] = pct

        # Holdout reduces the share available to the exposed variants. Rescale
        # the variant rollouts to reflect what's expected among exposed users
        # (which is what total_exposures measures). The holdout itself is dropped:
        # it never appears in total_exposures (the exposure query excludes it from
        # the WHERE IN clause), so including it in the chi-square would compare
        # observed=0 to expected>0 and falsely trigger SRM.
        if self.query.holdout:
            holdout_filters = self.query.holdout.filters
            holdout_pct = (
                holdout_filters[0].rollout_percentage
                if holdout_filters and holdout_filters[0].rollout_percentage is not None
                else 0
            )

            if holdout_pct > 0:
                scale = (100 - holdout_pct) / 100
                rollout_percentages = {k: v * scale for k, v in rollout_percentages.items()}

        # excluded_variants are not in the exposure chart, so they must not enter the chi-square.
        rollout_percentages = {k: v for k, v in rollout_percentages.items() if k not in self.excluded_variants}

        return sample_ratio_test(
            total_exposures,
            {key: pct for key, pct in rollout_percentages.items() if pct > 0 and key != MULTIPLE_VARIANT_KEY},
        )

    def _evaluate_bias_risk(
        self, total_exposures: dict[str, int], multiple_variant_handling: MultipleVariantHandling
    ) -> BiasRisk | None:
        # Shipping a variant rewrites the flag to 100/0, which would falsely trip the
        # uneven-split check on data collected under the original split. The warning also has
        # no action after the experiment stops, because both of its CTAs only apply while it runs.
        # Read the end from the query (the cache key), so that the running/stopped decision
        # matches the cached window.
        if self.window_end_date is not None:
            return None
        multivariate_data = (self.query.feature_flag.get("filters") or {}).get("multivariate") or {}
        flag_variants = multivariate_data.get("variants") or []
        return evaluate_bias_risk(
            rollout_percentages=[variant.get("rollout_percentage", 0) for variant in flag_variants],
            multiple_variant_handling=multiple_variant_handling,
            total_exposures=total_exposures,
        )

    def _can_read_flag_history(self) -> bool:
        # The flag's history stays behind the flag's own access controls and, for a token, the `activity_log:read`
        # scope, as on the health endpoint. A query runner can't see a token's scopes, so a request with any token reads
        # no history, and neither does a userless run or a principal that is not a user.
        if not isinstance(self.user, User) or get_query_tags().access_method is not None:
            return False
        # The cache key asks on every run, and each check loads the project's access rules.
        if self._flag_history_access is None or self._flag_history_access[0] != self.user.pk:
            try:
                readable = UserAccessControl(user=self.user, team=self.team).check_access_level_for_object(
                    self.experiment.feature_flag, required_level="viewer"
                )
            except Exception as error:
                # The answer feeds the cache key, so a failure here would fail the exposure query.
                capture_exception(error)
                readable = False
            self._flag_history_access = (self.user.pk, readable)
        return self._flag_history_access[1]

    def _runs_health_queries(self) -> bool:
        # The queries that explain a finding scan the exposure events, so they run only for a reader who sees the
        # findings. A userless run sees none. The answer stays out of the cache key: an async run computes the key
        # again in a worker, from that worker's flag definitions, and a key that disagrees with the web request's
        # makes every page load miss the cache.
        if not isinstance(self.user, User):
            return False
        if self._health_findings_shown is None or self._health_findings_shown[0] != self.user.pk:
            self._health_findings_shown = (self.user.pk, shows_health_findings(self.user, self.team))
        return self._health_findings_shown[1]

    def _flag_history(self) -> FlagHistory | FlagHistoryNotChecked | None:
        try:
            restrictions = get_restricted_properties_with_group_type_index_for_team(
                user=self.user if isinstance(self.user, User) else None, team_id=self.team.pk
            )
        except Exception as error:
            # The exposure answer must not fail for the history that only explains one finding.
            capture_exception(error)
            return None
        reader_access = ExperimentHealthReaderAccess(
            can_read_flag_history=self._can_read_flag_history(),
            # The reader is already querying the exposure events.
            can_query_events=True,
            denied_event_properties=split_restricted_property_names(restrictions).event,
        )
        return load_split_history(self.experiment, reader_access=reader_access)

    def _evaluate_health(self, exposures: ExposureTotals, exposure_params: ExposureQueryParams) -> ExperimentHealth:
        context = load_health_context(self.experiment, exposures)
        if reads_flag_history(context):
            context = replace(context, flag_history=self._flag_history())
        if not self._runs_health_queries():
            return evaluate_health(context, EXPOSURE_HEALTH_CHECKS)
        if reads_segments(context):
            segments = self._segments(exposure_params, segments_first_exposed_after(context))
            exposures = replace(exposures, segments=segments)
            context = replace(context, exposures=exposures)
        # Without test account filters on the project, the count without the filter is the same zero.
        if (
            exposure_params.filter_test_accounts
            and self.team.test_account_filters
            and reads_exposed_without_test_account_filter(context)
        ):
            exposed = self._exposed_without_test_account_filter(exposure_params)
            context = replace(context, exposures=replace(exposures, exposed_without_test_account_filter=exposed))
        return evaluate_health(context, EXPOSURE_HEALTH_CHECKS)

    def _segments(
        self, exposure_params: ExposureQueryParams, first_exposed_after: date | None
    ) -> tuple[ExposureSegment, ...] | None:
        query = self._query_builder(exposure_params).get_exposure_segments_query(
            TOP_SEGMENT_VALUES, first_exposed_after
        )
        rows = self._run_health_query("ExperimentExposureSegmentsQuery", query)
        if rows is None:
            return None
        exposed: dict[tuple[str, str, str], dict[str, int]] = {}
        for dimension, library, segment, variant, count in rows:
            exposed.setdefault((dimension, library, segment), {})[variant] = int(count)
        return tuple(
            ExposureSegment(
                dimension=ExposureSegmentDimension(dimension),
                value=segment,
                exposed_by_variant=counts,
                library=library or None,
            )
            for (dimension, library, segment), counts in exposed.items()
        )

    def _exposed_without_test_account_filter(self, exposure_params: ExposureQueryParams) -> int | None:
        query = self._query_builder(replace(exposure_params, filter_test_accounts=False)).get_exposed_count_query()
        rows = self._run_health_query("ExperimentExposuresWithoutTestAccountFilterQuery", query)
        if rows is None:
            return None
        return int(rows[0][0]) if rows else 0

    def _run_health_query(self, query_type: str, query: ast.SelectQuery) -> list[Any] | None:
        """The rows of a query that only explains a health finding. None when it fails, so that the finding keeps the
        wording without the explanation and the exposure answer doesn't fail."""
        try:
            with tags_context(experiment_query_surface="exposure_health", experiment_exposures_path="direct_scan"):
                response = execute_hogql_query(
                    query_type=query_type,
                    query=query,
                    team=self.team,
                    user=self.user,
                    timings=self.timings,
                    modifiers=self.modifiers,
                    # A profile that breaks on timeout returns partial counts, which would read as real ones.
                    settings=HogQLGlobalSettings(
                        max_execution_time=HEALTH_QUERY_TIMEOUT_SECONDS, timeout_overflow_mode="throw"
                    ),
                    # The exposure query runs both on a page load and in the background, and this query follows it.
                    workload=self.workload,
                )
        except ClickHouseQueryTimeOut:
            # The timeout above is the query's budget, so hitting it on a large project is expected, not an error.
            logger.warning("exposure_health_query_timed_out", experiment_id=self.experiment.id, query_type=query_type)
            return None
        except Exception as error:
            capture_exception(error)
            return None
        return response.results or []

    @staticmethod
    def _health_findings(health: ExperimentHealth) -> list[ExperimentExposureHealthFinding]:
        return [
            ExperimentExposureHealthFinding(
                code=ExperimentExposureHealthFindingCode(finding.code.value),
                subcode=finding.subcode,
                reason=finding.reason,
                severity=ExperimentExposureHealthFindingSeverity(finding.severity.value),
                title=finding.title,
                detail=finding.detail,
                evidence=dict(finding.evidence),
                actions=[ExperimentExposureHealthFindingActionKind(action.value) for action in finding.actions],
                diagnostic_ref=finding.diagnostic_ref,
            )
            for finding in health.findings
        ]

    @staticmethod
    def _health_checks(health: ExperimentHealth) -> list[ExperimentExposureHealthCheck]:
        return [
            ExperimentExposureHealthCheck(
                key=ExperimentExposureHealthCheckKey(check.key.value),
                name=check.name,
                status=ExperimentExposureHealthCheckStatus(check.status.value),
                reason=check.reason,
            )
            for check in health.checks
        ]

    @experiment_error_handler
    def _calculate(self) -> ExperimentExposureQueryResponse:
        tag_queries(
            experiment_id=self.query.experiment_id,
            experiment_name=self.query.experiment_name,
            experiment_feature_flag_key=self.feature_flag_key,
            product=Product.EXPERIMENTS,
            experiment_query_surface="exposures_timeseries",
            experiment_metric_events_path="not_applicable",
            # Set before _get_exposure_query() runs the exposures precompute build, so that build
            # sub-query inherits this id via the tag context and can be grouped under this read.
            experiment_query_group_id=uuid.uuid4(),
        )

        exposure_params = get_exposure_config_params_for_builder(
            self.exposure_criteria, self.team, self.experiment.start_date
        )
        # Set limit to avoid being cut-off by the default 100 rows limit
        query = self._get_exposure_query(exposure_params)
        query.limit = ast.Constant(value=QUERY_ROW_LIMIT)

        response = execute_hogql_query(
            query_type="ExperimentExposuresQuery",
            query=query,
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            settings=HogQLGlobalSettings(max_execution_time=600),
        )

        response.results = self._fill_date_gaps(response.results)
        variant_series: dict[str, ExperimentExposureTimeSeries] = {}

        variant_data: dict[str, dict[str, int]] = {}
        daily_exposures: dict[str, dict[date, int]] = {}
        for result in response.results:
            day, variant, count = result
            if variant not in variant_data:
                variant_data[variant] = {}
            variant_data[variant][day.isoformat()] = count
            daily_exposures.setdefault(variant, {})[day] = int(count)

        for variant, daily_counts in variant_data.items():
            sorted_days = sorted(daily_counts.keys())
            cumulative_counts = []
            running_total = 0

            for day in sorted_days:
                running_total += daily_counts[day]
                cumulative_counts.append(int(running_total))

            variant_series[variant] = ExperimentExposureTimeSeries(
                variant=variant, days=sorted_days, exposure_counts=cumulative_counts
            )

        # Keep the configured variant order, with MULTIPLE_VARIANT_KEY last
        ordered_timeseries = []
        for variant in self.variants:
            if variant in variant_series:
                ordered_timeseries.append(variant_series[variant])

        if MULTIPLE_VARIANT_KEY in variant_series:
            ordered_timeseries.append(variant_series[MULTIPLE_VARIANT_KEY])

        total_exposures = {}
        for variant, series in variant_series.items():
            total_exposures[variant] = int(series.exposure_counts[-1]) if series.exposure_counts else 0

        multiple_variant_handling = exposure_params.multiple_variant_handling
        sample_ratio_mismatch = self._calculate_srm(total_exposures)
        bias_risk = self._evaluate_bias_risk(total_exposures, multiple_variant_handling)
        health = self._evaluate_health(
            ExposureTotals(
                total_exposures=total_exposures,
                multiple_variant_handling=multiple_variant_handling,
                sample_ratio_mismatch_p_value=sample_ratio_mismatch.p_value if sample_ratio_mismatch else None,
                sample_ratio_expected=sample_ratio_mismatch.expected if sample_ratio_mismatch else {},
                daily_exposures=daily_exposures,
                hours_since_launch=self.experiment.hours_since_launch,
                counts_groups=aggregates_by_group(self.group_type_index),
            ),
            exposure_params,
        )

        return ExperimentExposureQueryResponse(
            timeseries=ordered_timeseries,
            total_exposures=total_exposures,
            date_range=self.date_range,
            sample_ratio_mismatch=sample_ratio_mismatch,
            bias_risk=bias_risk,
            health_findings=self._health_findings(health),
            health_checks=self._health_checks(health),
        )

    def to_query(self) -> ast.SelectQuery:
        raise ValueError("Cannot convert exposure query to raw query")

    def _fill_date_gaps(self, results):
        """
        Fills in every date of the analysis range for every configured variant, including a
        variant with zero exposures in the whole window. The response then carries an empty
        timeseries (all counts 0) for that variant instead of omitting it.
        """
        date_range = self._get_date_range()

        # A draft experiment has no start date, so it has no exposures.
        if not date_range.date_from:
            return []

        start_date = datetime.fromisoformat(date_range.date_from).date()
        end_date = datetime.fromisoformat(date_range.date_to).date() if date_range.date_to else datetime.now().date()

        result_dict = {}
        variants = set(self.variants)
        for day, variant, count in results:
            result_dict[(day, variant)] = count
            variants.add(variant)

        complete_results = []
        current_date = start_date
        while current_date <= end_date:
            for variant in variants:
                count = result_dict.get((current_date, variant), 0)
                complete_results.append((current_date, variant, count))
            current_date += timedelta(days=1)

        return complete_results

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        payload["experiment_exposures_response_version"] = 3
        # The sample ratio finding can name a split change from the flag's history, so a reader who can't read the
        # history, a userless run included, must not get a cached answer of one who can.
        if not self._can_read_flag_history():
            payload["flag_history_hidden"] = True
        return payload
