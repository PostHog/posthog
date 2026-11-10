from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import DateRange, ErrorTrackingQuery, HogQLQueryModifiers, PersonsOnEventsMode

from posthog.models import Team

from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner


class TestErrorTrackingQueryValidation(SimpleTestCase):
    @parameterized.expand([0, 200])
    def test_accepts_volume_resolution_boundaries(self, resolution: int) -> None:
        query = ErrorTrackingQuery(
            orderBy="last_seen", dateRange=DateRange(date_from="-7d"), volumeResolution=resolution
        )
        runner = ErrorTrackingQueryRunner(
            query=query,
            team=Team(id=1),
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED, useNewEventsSchema=False
            ),
        )
        runner.validate()

    @parameterized.expand([-1, 201])
    def test_rejects_volume_resolution_after_model_copy(self, resolution: int) -> None:
        query = ErrorTrackingQuery(
            orderBy="last_seen", dateRange=DateRange(date_from="-7d"), volumeResolution=20
        ).model_copy(update={"volumeResolution": resolution})
        runner = ErrorTrackingQueryRunner(
            query=query,
            team=Team(id=1),
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED, useNewEventsSchema=False
            ),
        )

        with self.assertRaises(ValidationError) as raised:
            runner.calculate()

        assert raised.exception.get_codes() == ["error_tracking_volume_resolution_out_of_range"]
