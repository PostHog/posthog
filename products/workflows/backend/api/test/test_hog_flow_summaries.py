import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User
from posthog.models.integration import Integration

from products.access_control.backend.models.access_control import AccessControl
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

TOTALS_FN = "products.workflows.backend.api.hog_flow_list.fetch_app_metric_totals_by_source"

WEBHOOK_AUTH_HEADER = "Bearer invented-webhook-token-7f3a"
EMAIL_BODY_MARKER = "invented-body-marker-9c1e"


def _trigger(trigger_type: str = "event") -> dict[str, Any]:
    return {"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": {"type": trigger_type}}


def _email(action_id: str, name: str, from_value: Any, subject: str = "", **config: Any) -> dict[str, Any]:
    return {
        "id": action_id,
        "name": name,
        "type": "function_email",
        "config": {
            "template_id": "template-email",
            "inputs": {
                "email": {
                    "value": {
                        "to": "{{ person.properties.email }}",
                        "from": from_value,
                        "subject": subject,
                        "preheader": f"Preheader {EMAIL_BODY_MARKER}",
                        "text": f"Text {EMAIL_BODY_MARKER}",
                        "html": f"<p>Html {EMAIL_BODY_MARKER}</p>",
                        "design": {"body": {"rows": [], "values": {"marker": EMAIL_BODY_MARKER}}},
                    }
                }
            },
            **config,
        },
    }


def _function(action_id: str, action_type: str, template_id: str, inputs: dict | None = None) -> dict[str, Any]:
    return {
        "id": action_id,
        "name": action_id,
        "type": action_type,
        "config": {"template_id": template_id, "inputs": inputs or {}},
    }


class TestHogFlowSummaries(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.news_sender = Integration.objects.create(
            team=self.team,
            kind="email",
            config={"email": "news@example.com", "name": "Acme News", "domain": "example.com", "verified": True},
        )
        self.updates_sender = Integration.objects.create(
            team=self.team,
            kind="email",
            config={"email": "updates@example.com", "name": "Acme Updates", "domain": "example.com", "verified": True},
        )
        totals_patcher = patch(TOTALS_FN, return_value={})
        self.fetch_totals = totals_patcher.start()
        self.addCleanup(totals_patcher.stop)

    def _summaries(self, query: str = "", **headers: str) -> Any:
        return self.client.get(f"/api/projects/{self.team.id}/hog_flows/summaries/{query}", **headers)

    def _mixed_flow(self) -> HogFlow:
        return HogFlow.objects.create(
            team=self.team,
            name="Onboarding",
            description="Owner: @dana",
            status=HogFlow.State.ACTIVE,
            created_by=self.user,
            actions=[
                _trigger("event"),
                _email(
                    "email_override",
                    "Welcome email",
                    {"integrationId": self.news_sender.id, "email": "hello@example.com", "name": "Dana at Acme"},
                    subject="Welcome to Acme, {{ person.properties.first_name }}",
                    template_uuid="0192f1a0-0000-7000-8000-000000000001",
                ),
                _email(
                    "email_rotation",
                    "Weekly digest",
                    {
                        "integrationId": self.news_sender.id,
                        "integrationIds": [self.news_sender.id, self.updates_sender.id],
                    },
                    subject="Your weekly digest",
                ),
                _function("sms_1", "function_sms", "template-twilio"),
                _function("slack_1", "function", "template-slack"),
                _function(
                    "webhook_1",
                    "function",
                    "template-webhook",
                    {
                        "url": {"value": "https://example.com/hook"},
                        "headers": {"value": {"Authorization": WEBHOOK_AUTH_HEADER}},
                    },
                ),
                {"id": "exit_node", "name": "Exit", "type": "exit", "config": {}},
            ],
            edges=[{"from": "trigger_node", "to": "email_override", "type": "continue"}],
        )

    def test_summaries_row_shape(self):
        flow = self._mixed_flow()
        self.fetch_totals.return_value = {str(flow.id): {"succeeded": 12, "failed": 3}}

        response = self._summaries()
        assert response.status_code == 200, response.json()
        (row,) = response.json()["results"]

        (list_row,) = self.client.get(f"/api/projects/{self.team.id}/hog_flows/").json()["results"]
        model_fields = ("id", "name", "description", "status", "origin_product", "created_by", "created_at")
        assert row == {
            **{key: list_row[key] for key in (*model_fields, "updated_at", "user_access_level")},
            "type": "messaging",
            "trigger_type": "event",
            "has_draft": False,
            "channels": ["email", "sms", "slack", "webhook"],
            "dispatches": [
                {"action_type": "function_email", "template_id": "template-email", "count": 2},
                {"action_type": "function_sms", "template_id": "template-twilio", "count": 1},
                {"action_type": "function", "template_id": "template-slack", "count": 1},
                {"action_type": "function", "template_id": "template-webhook", "count": 1},
            ],
            "email_steps": [
                {
                    "action_id": "email_override",
                    "name": "Welcome email",
                    "subject": "Welcome to Acme, {{ person.properties.first_name }}",
                    "from_addresses": ["hello@example.com"],
                    "from_name": "Dana at Acme",
                    "from_integration_ids": [self.news_sender.id],
                    "template_uuid": "0192f1a0-0000-7000-8000-000000000001",
                },
                {
                    "action_id": "email_rotation",
                    "name": "Weekly digest",
                    "subject": "Your weekly digest",
                    "from_addresses": ["news@example.com", "updates@example.com"],
                    "from_name": "Acme News",
                    "from_integration_ids": [self.news_sender.id, self.updates_sender.id],
                    "template_uuid": None,
                },
            ],
            "last_7_days": {"succeeded": 12, "failed": 3},
        }

        flow.draft = {"actions": [_trigger("schedule")]}
        flow.save()
        (row,) = self._summaries().json()["results"]
        assert (row["has_draft"], row["trigger_type"]) == (True, "event")

    def test_secrets_and_email_bodies_never_appear_in_a_listing(self):
        self._mixed_flow()

        summaries = self._summaries()
        mcp_list = self.client.get(f"/api/projects/{self.team.id}/hog_flows/", HTTP_X_POSTHOG_CLIENT="mcp")

        for response in (summaries, mcp_list):
            assert response.status_code == 200, response.json()
            body = response.content.decode()
            assert WEBHOOK_AUTH_HEADER not in body
            assert EMAIL_BODY_MARKER not in body
            assert "https://example.com/hook" not in body

    def test_row_for_a_large_email_body_stays_small(self):
        HogFlow.objects.create(
            team=self.team,
            name="Newsletter",
            created_by=self.user,
            actions=[
                _trigger(),
                _email(
                    "email_1",
                    "Monthly newsletter",
                    {"integrationId": self.news_sender.id},
                    subject="What's new this month",
                ),
            ],
        )
        flow = HogFlow.objects.get(team=self.team, name="Newsletter")
        flow.actions[1]["config"]["inputs"]["email"]["value"]["html"] = "<p>" + "x" * 20_000 + "</p>"
        flow.save()

        response = self._summaries()
        assert response.status_code == 200, response.json()
        (row,) = response.json()["results"]
        assert len(json.dumps(row)) < 1500

    @parameterized.expand([(workflow_type,) for workflow_type in ("messaging", "automation", "loop", "broadcast")])
    def test_row_type_matches_the_type_filter(self, workflow_type):
        HogFlow.objects.create(
            team=self.team, name="messaging", actions=[_function("a", "function_sms", "template-twilio")]
        )
        HogFlow.objects.create(
            team=self.team, name="automation", actions=[_function("a", "function", "template-webhook")]
        )
        HogFlow.objects.create(
            team=self.team,
            name="loop",
            origin_product="loops",
            actions=[_function("a", "function_sms", "template-twilio")],
        )
        HogFlow.objects.create(
            team=self.team,
            name="broadcast",
            origin_product="broadcasts",
            actions=[_email("a", "Announcement", "news@example.com")],
        )

        rows = self._summaries().json()["results"]
        filtered = self._summaries(f"?type={workflow_type}").json()["results"]

        assert {row["name"] for row in filtered} == {row["name"] for row in rows if row["type"] == workflow_type}
        assert {row["name"] for row in filtered} == {workflow_type}

    def test_trigger_type_follows_the_trigger_action_over_the_legacy_column(self):
        HogFlow.objects.create(
            team=self.team, name="Disagrees", trigger={"type": "event"}, actions=[_trigger("webhook")]
        )
        HogFlow.objects.create(team=self.team, name="Legacy", trigger={"type": "schedule"}, actions=[])

        rows = {row["name"]: row["trigger_type"] for row in self._summaries().json()["results"]}
        assert rows == {"Disagrees": "webhook", "Legacy": "schedule"}

        for trigger_type, expected in (("webhook", {"Disagrees"}), ("event", set()), ("schedule", {"Legacy"})):
            response = self._summaries(f"?trigger_type={trigger_type}")
            assert {row["name"] for row in response.json()["results"]} == expected, trigger_type

    @parameterized.expand(
        [
            ("override_wins", "override", ["hello@example.com"], "Acme News"),
            ("integration_resolves", "single", ["news@example.com"], "Acme News"),
            ("rotation_lists_every_address", "rotation", ["news@example.com", "updates@example.com"], "Acme News"),
            ("deleted_integration_is_skipped", "deleted", ["updates@example.com"], "Acme Updates"),
            ("legacy_string_from", "legacy", ["legacy@example.com"], None),
            ("other_team_integration_never_resolves", "other_team", [], None),
        ]
    )
    def test_sender_resolution(self, _name, sender, expected_addresses, expected_name):
        deleted = Integration.objects.create(team=self.team, kind="email", config={"email": "gone@example.com"})
        deleted_id = deleted.id
        deleted.delete()
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        foreign = Integration.objects.create(
            team=other_team, kind="email", config={"email": "foreign@example.com", "name": "Foreign"}
        )
        from_value = {
            "override": {"integrationId": self.news_sender.id, "email": "hello@example.com"},
            "single": {"integrationId": self.news_sender.id},
            "rotation": {"integrationId": self.news_sender.id, "integrationIds": [self.updates_sender.id]},
            "deleted": {"integrationIds": [deleted_id, self.updates_sender.id]},
            "legacy": "legacy@example.com",
            "other_team": {"integrationId": foreign.id},
        }[sender]
        HogFlow.objects.create(team=self.team, name="Sender", actions=[_email("email_1", "Email", from_value)])

        (row,) = self._summaries().json()["results"]
        (step,) = row["email_steps"]
        assert (step["from_addresses"], step["from_name"]) == (expected_addresses, expected_name)

    def test_totals_outage_returns_rows_without_totals(self):
        self._mixed_flow()
        self.fetch_totals.side_effect = RuntimeError("metrics store unavailable")

        response = self._summaries()
        assert response.status_code == 200, response.json()
        assert [row["last_7_days"] for row in response.json()["results"]] == [None]

    def test_workflow_without_metrics_gets_zero_totals(self):
        self._mixed_flow()
        self.fetch_totals.return_value = {"00000000-0000-0000-0000-000000000000": {"succeeded": 9, "failed": 9}}

        (row,) = self._summaries().json()["results"]
        assert row["last_7_days"] == {"succeeded": 0, "failed": 0}

    def test_other_teams_workflows_are_absent(self):
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        HogFlow.objects.create(team=other_team, name="Theirs")
        HogFlow.objects.create(team=self.team, name="Ours")

        assert [row["name"] for row in self._summaries().json()["results"]] == ["Ours"]

    def test_query_count_is_constant_in_the_row_count(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)

        def query_count(rows: int) -> int:
            HogFlow.objects.filter(team=self.team).delete()
            for index in range(rows):
                creator = User.objects.create_and_join(self.organization, f"author-{uuid4().hex}@example.com", None)
                flow = HogFlow.objects.create(
                    team=self.team,
                    name=f"Flow {index}",
                    created_by=creator,
                    draft={"actions": []},
                    actions=[
                        _trigger(),
                        _email(
                            "email_1",
                            "Email",
                            {"integrationId": self.news_sender.id, "integrationIds": [self.updates_sender.id]},
                        ),
                    ],
                )
                AccessControl.objects.create(
                    team=self.team,
                    resource="hog_flow",
                    resource_id=str(flow.id),
                    access_level="editor",
                    organization_member=membership,
                )
            with CaptureQueriesContext(connection) as queries:
                response = self._summaries()
            assert response.status_code == 200
            assert len(response.json()["results"]) == rows
            return len(queries)

        query_count(2)
        assert query_count(2) == query_count(20)

    def test_mcp_list_query_count_is_constant_in_the_row_count(self):
        def query_count(rows: int) -> int:
            HogFlow.objects.filter(team=self.team).delete()
            for index in range(rows):
                HogFlow.objects.create(
                    team=self.team,
                    name=f"Flow {index}",
                    created_by=self.user,
                    actions=[_trigger(), _email("email_1", "Email", {"integrationId": self.news_sender.id})],
                )
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/", HTTP_X_POSTHOG_CLIENT="mcp")
            assert len(response.json()["results"]) == rows
            return len(queries)

        query_count(2)
        assert query_count(2) == query_count(20)

    def test_pagination_caps_the_limit_and_pages_stably(self):
        HogFlow.objects.bulk_create([HogFlow(team=self.team, name=f"Flow {index}") for index in range(1001)])
        HogFlow.objects.filter(team=self.team).update(updated_at=datetime(2026, 1, 1, tzinfo=UTC))

        capped = self._summaries("?limit=5000").json()
        assert len(capped["results"]) == 1000
        assert capped["next"] is not None
        assert self._summaries().json()["count"] == 1001

        seen: list[str] = []
        page = self._summaries("?limit=400").json()
        while True:
            seen.extend(row["id"] for row in page["results"])
            if page["next"] is None:
                break
            page = self.client.get(page["next"]).json()
        assert len(seen) == len(set(seen)) == 1001

    def test_summaries_response_is_gzipped_and_the_full_list_is_not(self):
        for _ in range(3):
            self._mixed_flow()

        summaries = self._summaries(HTTP_ACCEPT_ENCODING="gzip")
        full_list = self.client.get(f"/api/projects/{self.team.id}/hog_flows/", HTTP_ACCEPT_ENCODING="gzip")
        environments = self.client.get(
            f"/api/environments/{self.team.id}/hog_flows/summaries/", HTTP_ACCEPT_ENCODING="gzip"
        )

        assert summaries.get("Content-Encoding") == "gzip"
        assert environments.get("Content-Encoding") == "gzip"
        assert full_list.status_code == 200
        assert full_list.get("Content-Encoding") is None

    def test_personal_api_key_with_workflow_read_can_list_summaries(self):
        self._mixed_flow()
        api_key = self.create_personal_api_key_with_scopes(["hog_flow:read"])
        self.client.logout()

        response = self._summaries(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        assert response.status_code == 200, response.json()
        assert len(response.json()["results"]) == 1
