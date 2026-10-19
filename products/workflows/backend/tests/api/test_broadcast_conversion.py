from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog

from products.workflows.backend.models import HogFlow

TRIGGER = {"id": "trigger_node", "name": "Audience", "type": "trigger", "config": {"type": "batch", "filters": {}}}
EMAIL = {"id": "email_node", "name": "Email", "type": "function_email", "config": {"inputs": {}}}
EXIT = {"id": "exit_node", "name": "Exit", "type": "exit", "config": {}}
DELAY = {"id": "delay_node", "name": "Delay", "type": "delay", "config": {"delay_duration": "1h"}}
EDGES = [
    {"from": "trigger_node", "to": "email_node", "type": "continue"},
    {"from": "email_node", "to": "exit_node", "type": "continue"},
]


class TestBroadcastConversionAPI(APIBaseTest):
    def _flow(self, **overrides: Any) -> HogFlow:
        fields: dict[str, Any] = {
            "team": self.team,
            "name": "Monthly update",
            "status": "draft",
            "exit_condition": "exit_only_at_end",
            "trigger": TRIGGER["config"],
            "actions": [TRIGGER, EMAIL, EXIT],
            "edges": EDGES,
            **overrides,
        }
        return HogFlow.objects.create(**fields)

    def _candidate_ids(self) -> list[str]:
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/broadcast_conversion_candidates/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return [row["id"] for row in response.json()["results"]]

    def _convert(self, flow: HogFlow) -> Any:
        return self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow.id}/convert_to_broadcast/")

    @parameterized.expand(
        [
            ("draft", {}, True),
            ("active", {"status": "active"}, True),
            ("archived", {"status": "archived"}, False),
            ("already a broadcast", {"origin_product": "broadcasts"}, False),
            ("exit on conversion", {"exit_condition": "exit_on_conversion"}, False),
            ("staged draft", {"draft": {"actions": [TRIGGER, EMAIL, EXIT]}}, False),
            (
                "event trigger",
                {"actions": [{**TRIGGER, "config": {"type": "event", "filters": {}}}, EMAIL, EXIT]},
                False,
            ),
            (
                "account audience",
                {
                    "actions": [
                        {**TRIGGER, "config": {"type": "batch", "filters": {"audience_type": "accounts"}}},
                        EMAIL,
                        EXIT,
                    ]
                },
                False,
            ),
            ("extra step", {"actions": [TRIGGER, EMAIL, DELAY, EXIT]}, False),
            ("edge that skips the email", {"edges": [*EDGES, {"from": "trigger_node", "to": "exit_node"}]}, False),
        ]
    )
    def test_only_workflows_the_broadcast_editor_can_own_are_offered_and_converted(
        self, _name: str, overrides: dict[str, Any], convertible: bool
    ) -> None:
        flow = self._flow(**overrides)

        assert (str(flow.id) in self._candidate_ids()) is convertible

        response = self._convert(flow)
        flow.refresh_from_db()
        if convertible:
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert response.json() == {"id": str(flow.id), "origin_product": "broadcasts"}
            assert flow.origin_product == "broadcasts"
            assert ActivityLog.objects.filter(
                team_id=self.team.id, item_id=str(flow.id), activity="converted_to_broadcast"
            ).exists()
            assert str(flow.id) not in self._candidate_ids()
        else:
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            assert flow.origin_product == overrides.get("origin_product")

    def test_candidates_stop_at_the_cap_and_say_more_exist(self) -> None:
        newest = self._flow(name="Newest")
        self._flow(name="Broken", edges=[{"from": "trigger_node", "to": "exit_node"}])
        self._flow(name="Oldest")
        HogFlow.objects.filter(pk=newest.pk).update(updated_at="2030-01-01T00:00:00Z")

        with patch("products.workflows.backend.presentation.views.hog_flow.BROADCAST_CONVERSION_CANDIDATE_LIMIT", 1):
            response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/broadcast_conversion_candidates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "has_more": True,
            "results": [{"id": str(newest.id), "name": "Newest", "status": "draft"}],
        }
