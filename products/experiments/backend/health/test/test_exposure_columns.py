from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode, PropertyGroupsMode

from posthog.models.event.new_events_schema import events_route_scope
from posthog.models.property import TableColumn

from products.experiments.backend.health.exposure_columns import load_exposure_reads
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.clickhouse.materialized_columns.columns import MaterializedColumn, MaterializedColumnDetails

ON_EVENTS = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
JOINED = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED


def _column(table_column: TableColumn, key: str) -> MaterializedColumn:
    return MaterializedColumn(
        name=f"mat_{key}", details=MaterializedColumnDetails(table_column, key, is_disabled=False), is_nullable=False
    )


MATERIALIZED_COLUMNS = {
    "events": {
        ("plan", "properties"): _column("properties", "plan"),
        ("tier", "person_properties"): _column("person_properties", "tier"),
    },
    "person": {("tier", "properties"): _column("properties", "tier")},
}


def _filter(key: str, property_type: str, **rest: Any) -> dict[str, Any]:
    return {"key": key, "type": property_type, "operator": "is_set", **rest}


class TestLoadExposureReads(BaseTest):
    def _experiment(
        self, *, filter_test_accounts: bool = True, flag_filters: dict[str, Any] | None = None
    ) -> Experiment:
        return Experiment.objects.create(
            team=self.team,
            name="Pricing page",
            feature_flag=FeatureFlag.objects.create(
                team=self.team, key="pricing-page", created_by=self.user, filters=flag_filters or {}
            ),
            # Long enough for the team's precompute rules to apply.
            start_date=timezone.now() - timedelta(days=3),
            exposure_criteria={
                "filterTestAccounts": filter_test_accounts,
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "$pageview",
                    "properties": [
                        _filter("plan", "event"),
                        _filter("$plan_source", "event"),
                        _filter("campaign", "event"),
                        _filter("tier", "person"),
                        _filter("$initial_os", "person"),
                        _filter("industry", "group", group_type_index=0),
                        # None of these reads the JSON: the query reads the flag key anyway, and the others are columns.
                        _filter("$feature_flag", "event"),
                        _filter("$elements_chain", "event"),
                        _filter("$virt_is_bot", "event"),
                        _filter("distinct_id", "person"),
                        _filter("$group_key", "group", group_type_index=0),
                    ],
                },
            },
        )

    @parameterized.expand(
        [
            (
                "without_property_groups",
                ON_EVENTS,
                None,
                False,
                True,
                [
                    "event:$plan_source",
                    "event:campaign",
                    "person:$initial_os",
                    "group:industry",
                    "person:email (test account)",
                ],
            ),
            (
                "property_groups_hold_the_custom_properties",
                ON_EVENTS,
                PropertyGroupsMode.OPTIMIZED,
                False,
                True,
                ["event:$plan_source", "person:$initial_os", "group:industry"],
            ),
            (
                "persons_joined",
                JOINED,
                None,
                False,
                True,
                [
                    "event:$plan_source",
                    "event:campaign",
                    "person:$initial_os",
                    "group:industry",
                    "person:email (test account)",
                ],
            ),
            (
                "native_events_table",
                ON_EVENTS,
                None,
                True,
                True,
                ["group:industry"],
            ),
            (
                "test_accounts_not_filtered",
                ON_EVENTS,
                None,
                False,
                False,
                ["event:$plan_source", "event:campaign", "person:$initial_os", "group:industry"],
            ),
        ]
    )
    def test_names_the_filters_that_read_all_the_properties(
        self,
        _name: str,
        persons_on_events_mode: PersonsOnEventsMode,
        property_groups_mode: PropertyGroupsMode | None,
        new_events_schema: bool,
        filter_test_accounts: bool,
        expected: list[str],
    ) -> None:
        self.team.modifiers = {
            "personsOnEventsMode": persons_on_events_mode,
            "propertyGroupsMode": property_groups_mode,
        }
        self.team.test_account_filters = [_filter("email", "person"), _filter("tier", "person")]
        self.team.save()
        experiment = self._experiment(filter_test_accounts=filter_test_accounts)

        with (
            events_route_scope(HogQLQueryModifiers(useNewEventsSchema=new_events_schema)),
            patch(
                "posthog.clickhouse.materialized_columns.get_enabled_materialized_columns_by_table",
                return_value=MATERIALIZED_COLUMNS,
            ),
        ):
            reads = load_exposure_reads(experiment)

        assert reads is not None
        self.assertEqual(
            [
                f"{found.type}:{found.key}{' (test account)' if found.test_account else ''}"
                for found in reads.filters_without_column
            ],
            expected,
        )

    @parameterized.expand(
        [
            ("project_precomputes", True, {}, True),
            ("project_does_not_precompute", False, {}, False),
            ("experiment_counts_groups", True, {"aggregation_group_type_index": 0}, False),
        ]
    )
    def test_says_whether_the_metric_queries_read_precomputed_exposures(
        self, _name: str, precomputes: bool, flag_filters: dict[str, Any], expected: bool
    ) -> None:
        TeamExperimentsConfig.objects.update_or_create(
            team=self.team, defaults={"experiment_precomputation_enabled": precomputes}
        )

        reads = load_exposure_reads(self._experiment(flag_filters=flag_filters))

        assert reads is not None
        self.assertEqual(reads.precomputed, expected)
