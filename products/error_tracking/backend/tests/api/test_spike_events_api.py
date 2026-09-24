from datetime import UTC, datetime

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingSpikeEvent
from products.error_tracking.backend.presentation.views.spike_events import ErrorTrackingSpikeEventListQuerySerializer

ISSUE_ID = "0195fd8a-7c4e-7a1b-9f4e-2b3c4d5e6f70"


class TestErrorTrackingSpikeEventListQuerySerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("date_to_quote", {"date_to": "'"}, "date_to"),
            ("date_to_integer", {"date_to": "1"}, "date_to"),
            ("date_from_relative", {"date_from": "-7d"}, "date_from"),
            ("issue_ids_not_a_uuid", {"issue_ids": "not-a-uuid"}, "issue_ids"),
            ("issue_ids_one_bad_entry", {"issue_ids": f"{ISSUE_ID},nope"}, "issue_ids"),
        ]
    )
    def test_malformed_filter_is_rejected(self, _name: str, data: dict[str, str], field: str):
        serializer = ErrorTrackingSpikeEventListQuerySerializer(data=data)

        assert not serializer.is_valid()
        assert field in serializer.errors

    @parameterized.expand(
        [
            ("no_filters", {}, {}),
            (
                "blank_filters",
                {"date_to": "", "issue_ids": "", "order_by": ""},
                {"date_to": None, "issue_ids": [], "order_by": ""},
            ),
            ("issue_ids_list", {"issue_ids": f" {ISSUE_ID} ,"}, {"issue_ids": [ISSUE_ID]}),
            (
                "iso_timestamps",
                {"date_from": "2026-01-01T00:00:00Z", "date_to": "2026-01-03T00:00:00Z"},
                {
                    "date_from": datetime(2026, 1, 1, tzinfo=UTC),
                    "date_to": datetime(2026, 1, 3, tzinfo=UTC),
                },
            ),
        ]
    )
    def test_accepted_filter_is_normalized(self, _name: str, data: dict[str, str], expected: dict[str, object]):
        serializer = ErrorTrackingSpikeEventListQuerySerializer(data=data)

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data == expected


class TestSpikeEventsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.issue = ErrorTrackingIssue.objects.create(team=self.team)
        self.spike = ErrorTrackingSpikeEvent.objects.create(
            team=self.team,
            issue=self.issue,
            detected_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            computed_baseline=5.0,
            current_bucket_value=100,
        )

    def _list(self, query: str = ""):
        return self.client.get(f"/api/environments/{self.team.id}/error_tracking/spike_events/{query}")

    def test_malformed_date_filter_is_rejected(self):
        response = self._list("?date_to='")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

    @parameterized.expand(
        [
            ("range_around_the_spike", "?date_from=2026-01-01T00:00:00Z&date_to=2026-01-03T00:00:00Z", True),
            ("range_after_the_spike", "?date_from=2026-02-01T00:00:00Z", False),
            ("matching_issue", f"?issue_ids={{issue_id}}", True),
        ]
    )
    def test_filter_selects_the_expected_spikes(self, _name: str, query: str, expect_spike: bool):
        response = self._list(query.format(issue_id=self.issue.id))

        assert response.status_code == status.HTTP_200_OK, response.content
        expected = [str(self.spike.id)] if expect_spike else []
        assert [result["id"] for result in response.json()["results"]] == expected
