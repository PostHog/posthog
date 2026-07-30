from datetime import UTC, datetime
from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, flush_persons_and_events

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    EventsNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentQueryResponse,
)

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.test.persons import create_person

from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.hogql_queries.experiment_query_builder import (
    ExperimentQueryBuilder,
    get_exposure_config_params_for_builder,
)
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.exposure_query_logic import get_exposure_exclusions
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest


@override_settings(IN_UNIT_TESTING=True)
class TestExposureExclusions(ExperimentQueryRunnerBaseTest):
    def _create_exposed_person(self, distinct_id: str, variant: str, flag_key: str, person_properties: dict) -> None:
        # Exposure and purchase land first, the person properties are set afterwards. That's the
        # shape that matters: the events carry no snapshot of the properties, so anything
        # resolving person properties off the event can't see them.
        create_person(team=self.team, distinct_ids=[distinct_id], properties=person_properties)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id=distinct_id,
            timestamp="2020-01-02T12:00:00Z",
            properties={
                f"$feature/{flag_key}": variant,
                "$feature_flag_response": variant,
                "$feature_flag": flag_key,
            },
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id=distinct_id,
            timestamp="2020-01-02T12:01:00Z",
            properties={f"$feature/{flag_key}": variant},
        )

    def _run(self, experiment) -> ExperimentQueryResponse:
        metric = ExperimentMeanMetric(source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL))
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()
        runner = ExperimentQueryRunner(
            query=ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric),
            team=self.team,
        )
        return cast(ExperimentQueryResponse, runner.calculate())

    def _exposed_counts(self, result: ExperimentQueryResponse) -> dict[str, float]:
        assert result.baseline is not None
        assert result.variant_results is not None
        return {
            "control": result.baseline.number_of_samples,
            **{variant.key: variant.number_of_samples for variant in result.variant_results},
        }

    @freeze_time("2020-01-01T12:00:00Z")
    def test_person_property_exclusion_removes_people_exposed_before_the_marker_was_set(self):
        # The headline case: someone withdraws consent after being exposed and converting. Their
        # exposure is already ingested, so a filter resolving against the event would leave them
        # in the denominator. The exclusion has to reach current person state.
        feature_flag = self.create_feature_flag(key="consent-withdrawal")
        experiment = self.create_experiment(feature_flag=feature_flag)

        for i in range(6):
            self._create_exposed_person(f"user_control_{i}", "control", feature_flag.key, {})
        for i in range(6):
            # Two test-group people withdrew consent after they were exposed.
            withdrawn = {"consent_withdrawn": True} if i < 2 else {}
            self._create_exposed_person(f"user_test_{i}", "test", feature_flag.key, withdrawn)
        flush_persons_and_events()

        assert self._exposed_counts(self._run(experiment)) == {"control": 6, "test": 6}

        experiment.exposure_criteria = {
            "exclusions": [{"key": "consent_withdrawn", "type": "person", "value": ["true"], "operator": "exact"}]
        }
        assert self._exposed_counts(self._run(experiment)) == {"control": 6, "test": 4}

    @freeze_time("2020-01-01T12:00:00Z")
    def test_cohort_exclusion_removes_members(self):
        feature_flag = self.create_feature_flag(key="consent-withdrawal-cohort")
        experiment = self.create_experiment(feature_flag=feature_flag)

        for i in range(6):
            self._create_exposed_person(f"user_control_{i}", "control", feature_flag.key, {})
        for i in range(6):
            self._create_exposed_person(
                f"user_test_{i}", "test", feature_flag.key, {"consent_withdrawn": True} if i < 2 else {}
            )
        flush_persons_and_events()

        cohort = Cohort.objects.create(
            team=self.team,
            name="Withdrew consent",
            groups=[
                {"properties": [{"key": "consent_withdrawn", "type": "person", "value": ["true"], "operator": "exact"}]}
            ],
        )
        cohort.calculate_people_ch(pending_version=0)

        experiment.exposure_criteria = {"exclusions": [{"key": "id", "type": "cohort", "value": cohort.pk}]}
        assert self._exposed_counts(self._run(experiment)) == {"control": 6, "test": 4}

    @parameterized.expand(
        [
            ("no_exclusions", None, True),
            (
                "with_exclusions",
                [{"key": "consent_withdrawn", "type": "person", "value": ["true"], "operator": "exact"}],
                False,
            ),
        ]
    )
    @freeze_time("2020-01-01T12:00:00Z")
    def test_exclusions_bypass_the_precomputed_exposure_table(self, _name, exclusions, expects_precomputed_read):
        # Precomputed exposures are built once and cached for weeks, so reading them would pin
        # exclusion membership to build time, which is the one thing retroactive exclusion
        # can't tolerate.
        feature_flag = self.create_feature_flag(key=f"precompute-{_name.replace('_', '-')}")
        criteria = {"exclusions": exclusions} if exclusions is not None else None
        exposure_config, multiple_variant_handling, filter_test_accounts = get_exposure_config_params_for_builder(
            criteria
        )

        builder = ExperimentQueryBuilder(
            team=self.team,
            feature_flag_key=feature_flag.key,
            exposure_config=exposure_config,
            filter_test_accounts=filter_test_accounts,
            multiple_variant_handling=multiple_variant_handling,
            variants=["control", "test"],
            date_range_query=QueryDateRange(
                date_range=DateRange(date_from="2020-01-01", date_to="2020-01-14"),
                team=self.team,
                interval=None,
                now=datetime(2020, 1, 14, tzinfo=UTC),
            ),
            entity_key="person_id",
            metric=ExperimentMeanMetric(source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL)),
            exposure_exclusions=get_exposure_exclusions(criteria),
        )
        builder.preaggregation_job_ids = ["some-job-id"]
        query = builder._exposure_query_builder().select_query()

        assert query.select_from is not None
        reads_precomputed = "experiment_exposures_preaggregated" in str(query.select_from.table)
        assert reads_precomputed is expects_precomputed_read
