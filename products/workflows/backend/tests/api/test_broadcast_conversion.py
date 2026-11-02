from collections.abc import Callable
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.integration import SANDBOX_EMAIL_INTEGRATION_ID, SANDBOX_EMAIL_PROVIDER, Integration

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
            (
                "email step without a sender object",
                {"actions": [TRIGGER, {**EMAIL, "config": {"inputs": {"email": {"value": "draft"}}}}, EXIT]},
                True,
            ),
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

    @parameterized.expand(
        [
            ("sandbox sender", {"integrationId": "sandbox"}, int, False),
            ("sandbox sender stored as a whole-number float", {"integrationId": "sandbox"}, float, False),
            ("sandbox sender stored as a string", {"integrationId": "sandbox"}, str, False),
            ("sandbox sender in a rotation", {"integrationIds": ["own", "sandbox"]}, int, False),
            ("own sender", {"integrationId": "own"}, int, True),
            (
                "own rotation with a stale sandbox fallback",
                {"integrationId": "sandbox", "integrationIds": ["own"]},
                int,
                True,
            ),
        ]
    )
    def test_a_workflow_sending_through_the_sandbox_sender_does_not_become_a_broadcast(
        self, _name: str, sender: dict[str, Any], stored_as: Callable[[int], Any], convertible: bool
    ) -> None:
        integration_ids = {
            "sandbox": Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id=SANDBOX_EMAIL_INTEGRATION_ID,
                config={"provider": SANDBOX_EMAIL_PROVIDER, "verified": True},
            ).id,
            "own": Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id="sender@example.com",
                config={"provider": "ses", "domain": "example.com", "verified": True},
            ).id,
        }
        sender_from = {
            key: [stored_as(integration_ids[name]) for name in value]
            if isinstance(value, list)
            else stored_as(integration_ids[value])
            for key, value in sender.items()
        }
        email = {**EMAIL, "config": {"inputs": {"email": {"value": {"from": sender_from}}}}}
        flow = self._flow(actions=[TRIGGER, email, EXIT])

        assert (str(flow.id) in self._candidate_ids()) is convertible
        response = self._convert(flow)
        assert (response.status_code == status.HTTP_200_OK) is convertible, response.json()

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
