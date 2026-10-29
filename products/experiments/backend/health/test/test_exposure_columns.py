from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.models.event.new_events_schema import events_route_scope

from products.experiments.backend.health import exposure_columns
from products.experiments.backend.health.exposure_columns import load_exposure_filters_without_column
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

MATERIALIZED = {("events", "properties", "plan"), ("events", "person_properties", "tier")}


def _materialized_column(table: str, table_column: str, property_name: str) -> MagicMock | None:
    return MagicMock() if (table, table_column, property_name) in MATERIALIZED else None


class TestExposureFiltersWithoutColumn(BaseTest):
    @parameterized.expand(
        [
            (
                "person_properties_on_events",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                False,
                ["event:utm_campaign", "group:industry"],
            ),
            (
                "persons_joined",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
                False,
                ["event:utm_campaign", "person:tier", "group:industry"],
            ),
            (
                "native_events_table",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                True,
                ["group:industry"],
            ),
        ]
    )
    def test_looks_up_the_column_that_the_exposure_query_reads(
        self, _name: str, persons_on_events_mode: PersonsOnEventsMode, new_events_schema: bool, expected: list[str]
    ) -> None:
        self.team.modifiers = {"personsOnEventsMode": persons_on_events_mode}
        self.team.save()
        experiment = Experiment.objects.create(
            team=self.team,
            name="Pricing page",
            feature_flag=FeatureFlag.objects.create(team=self.team, key="pricing-page", created_by=self.user),
            start_date=timezone.now(),
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "$pageview",
                    "properties": [
                        {"key": "plan", "type": "event", "operator": "exact", "value": ["pro"]},
                        {"key": "utm_campaign", "type": "event", "operator": "is_set"},
                        {"key": "tier", "type": "person", "operator": "exact", "value": ["gold"]},
                        {"key": "industry", "type": "group", "group_type_index": 0, "operator": "is_set"},
                        {"key": "$group_key", "type": "group", "group_type_index": 0, "operator": "is_set"},
                    ],
                }
            },
        )

        with (
            events_route_scope(HogQLQueryModifiers(useNewEventsSchema=new_events_schema)),
            patch.object(exposure_columns, "get_materialized_column_for_property", side_effect=_materialized_column),
        ):
            filters = load_exposure_filters_without_column(experiment)

        assert filters is not None
        self.assertEqual([f"{exposure_filter.type}:{exposure_filter.key}" for exposure_filter in filters], expected)
