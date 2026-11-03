from collections.abc import Callable
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode, PropertyGroupsMode

from posthog.models.event.new_events_schema import events_route_scope
from posthog.models.property import TableColumn
from posthog.schema_enums import MaterializationMode

from products.actions.backend.models.action import Action
from products.experiments.backend.health.context import ExposureFilterSource
from products.experiments.backend.health.exposure_columns import load_filters_without_column
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.clickhouse.materialized_columns.columns import MaterializedColumn, MaterializedColumnDetails

ON_EVENTS = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
JOINED = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED
_SOURCE_LABELS = {
    ExposureFilterSource.EXPOSURE_CRITERIA: "",
    ExposureFilterSource.EXPOSURE_ACTION: " (action)",
    ExposureFilterSource.TEST_ACCOUNTS: " (test account)",
}


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


class TestLoadFiltersWithoutColumn(BaseTest):
    def _experiment(self, *, filter_test_accounts: bool = True) -> Experiment:
        return Experiment.objects.create(
            team=self.team,
            name="Pricing page",
            feature_flag=FeatureFlag.objects.create(
                team=self.team, key="pricing-page", created_by=self.user, filters={}
            ),
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
            (
                "persons_joined_materialization_disabled",
                JOINED,
                None,
                False,
                True,
                [
                    "event:plan",
                    "event:$plan_source",
                    "event:campaign",
                    "person:tier",
                    "person:$initial_os",
                    "group:industry",
                    "person:email (test account)",
                    "person:tier (test account)",
                ],
                MaterializationMode.DISABLED,
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
        materialization_mode: MaterializationMode | None = None,
    ) -> None:
        self.team.modifiers = {
            "personsOnEventsMode": persons_on_events_mode,
            "propertyGroupsMode": property_groups_mode,
            "materializationMode": materialization_mode,
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
            filters = load_filters_without_column(experiment)

        assert filters is not None
        self.assertEqual(
            [f"{found.type}:{found.key}{_SOURCE_LABELS[found.source]}" for found in filters],
            expected,
        )

    @parameterized.expand(
        [
            ("criteria_do_not_parse", {"exposure_config": {"kind": "Unknown"}}, None),
            (
                "criteria_have_no_exposure_query",
                {
                    "exposure_config": {
                        "kind": "ExperimentWarehouseNativeExposureConfig",
                        "connection_id": "source",
                        "query": "SELECT 1",
                    }
                },
                None,
            ),
            (
                "criteria_have_no_filters",
                {"filterTestAccounts": False},
                (),
            ),
        ]
    )
    def test_criteria_without_a_filter_to_name(
        self, _name: str, exposure_criteria: dict[str, Any], expected: tuple[()] | None
    ) -> None:
        experiment = self._experiment()
        experiment.exposure_criteria = exposure_criteria

        self.assertEqual(load_filters_without_column(experiment), expected)

    @parameterized.expand(
        [
            (
                "exposure_action",
                lambda action: {"exposure_config": action},
                ["event:campaign (action)", "event:$current_url (action)", "event:source (action)"],
            ),
            (
                "activation_action",
                lambda action: {"exposure_config": None, "activation_config": action},
                ["event:campaign (action)", "event:$current_url (action)", "event:source (action)"],
            ),
            ("deleted_action", lambda action: {"exposure_config": {**action, "id": 0}}, ["event:source (action)"]),
        ]
    )
    def test_names_the_filters_of_an_action(
        self, _name: str, criteria: Callable[[dict[str, Any]], dict[str, Any]], expected: list[str]
    ) -> None:
        action = Action.objects.create(
            team=self.team,
            name="Started checkout",
            steps_json=[
                {"event": "checkout", "properties": [_filter("campaign", "event")]},
                {"event": "$pageview", "url": "/checkout", "properties": [_filter("$virt_is_bot", "event")]},
            ],
        )
        experiment = self._experiment()
        experiment.exposure_criteria = {
            "filterTestAccounts": False,
            **criteria(
                {"kind": "ActionsNode", "id": action.pk, "properties": [_filter("source", "event")]},
            ),
        }

        with events_route_scope(HogQLQueryModifiers(useNewEventsSchema=False)):
            filters = load_filters_without_column(experiment)

        assert filters is not None
        self.assertEqual([f"{found.type}:{found.key}{_SOURCE_LABELS[found.source]}" for found in filters], expected)

    def test_a_virtual_property_does_not_take_a_read_that_another_filter_names(self) -> None:
        self.team.test_account_filters = [_filter("$virt_is_bot", "event")]
        self.team.save()
        experiment = self._experiment()
        experiment.exposure_criteria = {
            "filterTestAccounts": True,
            "exposure_config": {
                "kind": "ExperimentEventExposureConfig",
                "event": "$pageview",
                "properties": [_filter("$lib", "event")],
            },
        }

        with events_route_scope(HogQLQueryModifiers(useNewEventsSchema=False)):
            filters = load_filters_without_column(experiment)

        assert filters is not None
        self.assertEqual(
            [f"{found.type}:{found.key}{_SOURCE_LABELS[found.source]}" for found in filters], ["event:$lib"]
        )
