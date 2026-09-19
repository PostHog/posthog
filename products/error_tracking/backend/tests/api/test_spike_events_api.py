from posthog.test.base import APIBaseTest

from django.http import QueryDict
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from products.error_tracking.backend.presentation.views.spike_events import SpikeEventsListQuerySerializer

VALID_UUID = "0195d3e0-0000-7000-8000-000000000001"


class TestSpikeEventsListQuerySerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("single", VALID_UUID, [VALID_UUID]),
            ("comma_separated", f"{VALID_UUID},{VALID_UUID}", [VALID_UUID, VALID_UUID]),
            ("whitespace_trimmed", f" {VALID_UUID} , ", [VALID_UUID]),
            ("empty_string", "", []),
        ]
    )
    def test_issue_ids_parsed(self, _name, raw, expected):
        serializer = SpikeEventsListQuerySerializer(data={"issue_ids": raw})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data.get("issue_ids", []) == expected

    @parameterized.expand(
        [
            ("issue_ids", "issue_ids="),
            ("date_from", "date_from="),
            ("date_to", "date_to="),
            ("order_by", "order_by="),
            ("every_param", "issue_ids=&date_from=&date_to=&order_by="),
        ]
    )
    def test_empty_params_are_ignored(self, _name, query_string):
        # The view validates `request.query_params`, a QueryDict that DRF reads as HTML input, so
        # empty values are dropped instead of validated. A client that always sends every param
        # must keep getting a 200, not a 400 on the blank ones.
        serializer = SpikeEventsListQuerySerializer(data=QueryDict(query_string))
        assert serializer.is_valid(), serializer.errors
        assert not any(
            serializer.validated_data.get(field) for field in ("issue_ids", "date_from", "date_to", "order_by")
        )

    def test_malformed_uuid_rejected(self):
        serializer = SpikeEventsListQuerySerializer(data={"issue_ids": "not-a-uuid"})
        assert not serializer.is_valid()
        assert "issue_ids" in serializer.errors

    def test_malformed_date_rejected(self):
        serializer = SpikeEventsListQuerySerializer(data={"date_from": "not-a-date"})
        assert not serializer.is_valid()
        assert "date_from" in serializer.errors

    def test_unknown_order_by_rejected(self):
        serializer = SpikeEventsListQuerySerializer(data={"order_by": "; DROP TABLE"})
        assert not serializer.is_valid()
        assert "order_by" in serializer.errors


class TestSpikeEventsListEndpoint(APIBaseTest):
    def _url(self, query: str = "") -> str:
        return f"/api/projects/{self.team.id}/error_tracking/spike_events/{query}"

    def test_malformed_issue_id_returns_400_not_500(self):
        # A bad UUID used to reach the ORM filter and surface as a generic 500.
        response = self.client.get(self._url("?issue_ids=not-a-uuid"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

    def test_valid_request_returns_200(self):
        response = self.client.get(self._url(f"?issue_ids={VALID_UUID}"))
        assert response.status_code == status.HTTP_200_OK, response.content
