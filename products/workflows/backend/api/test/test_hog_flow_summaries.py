import re
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from clickhouse_driver.errors import ServerException
from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User
from posthog.models.integration import Integration

from products.access_control.backend.models.access_control import AccessControl
from products.workflows.backend.api.hog_flow_list import HogFlowListRowSerializer
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

TOTALS_FN = "products.workflows.backend.api.hog_flow_list.fetch_app_metric_totals_by_source"

WEBHOOK_AUTH_HEADER = "Bearer invented-webhook-token-7f3a"
EMAIL_BODY_MARKER = "invented-body-marker-9c1e"


def _trigger(trigger_type: str = "event") -> dict[str, Any]:
    return {"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": {"type": trigger_type}}


def _email(
    action_id: str,
    name: str,
    from_value: Any,
    subject: str = "",
    html: str = f"<p>Html {EMAIL_BODY_MARKER}</p>",
    **config: Any,
) -> dict[str, Any]:
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
                        "html": html,
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

    def _summaries(self, query: str = "", **headers: Any) -> Any:
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
                    html="<p>" + "x" * 20_000 + "</p>",
                ),
            ],
        )

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
        HogFlow.objects.create(
            team=self.team,
            name="Two triggers",
            actions=[_trigger("event"), {**_trigger("schedule"), "id": "second_trigger"}],
        )

        rows = {row["name"]: row["trigger_type"] for row in self._summaries().json()["results"]}
        assert rows == {"Disagrees": "webhook", "Legacy": "schedule", "Two triggers": "event"}

        for trigger_type, expected in (
            ("webhook", {"Disagrees"}),
            ("event", {"Two triggers"}),
            ("schedule", {"Legacy"}),
        ):
            response = self._summaries(f"?trigger_type={trigger_type}")
            assert {row["name"] for row in response.json()["results"]} == expected, trigger_type
            response = self._summaries(f"?exclude_trigger_type={trigger_type}")
            assert {row["name"] for row in response.json()["results"]} == set(rows) - expected, trigger_type

    @parameterized.expand(
        [
            ("override_wins", "override", ["hello@example.com"], "Acme News", ["news"]),
            ("integration_resolves", "single", ["news@example.com"], "Acme News", ["news"]),
            (
                "rotation_lists_every_address",
                "rotation",
                ["news@example.com", "updates@example.com"],
                "Acme News",
                ["news", "updates"],
            ),
            ("rotation_replaces_primary", "rotation_only", ["updates@example.com"], "Acme Updates", ["updates"]),
            ("empty_rotation_uses_primary", "empty_rotation", ["news@example.com"], "Acme News", ["news"]),
            ("deleted_integration_is_skipped", "deleted", ["updates@example.com"], "Acme Updates", ["gone", "updates"]),
            ("legacy_string_from", "legacy", ["legacy@example.com"], None, []),
            ("legacy_named_string_from", "legacy_named", ["team@example.com"], "Acme Team", []),
            ("other_team_integration_never_resolves", "other_team", [], None, ["foreign"]),
        ]
    )
    def test_sender_resolution(self, _name, sender, expected_addresses, expected_name, expected_ids):
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
            "rotation": {
                "integrationId": self.news_sender.id,
                "integrationIds": [self.news_sender.id, self.updates_sender.id],
            },
            "rotation_only": {"integrationId": self.news_sender.id, "integrationIds": [self.updates_sender.id]},
            "empty_rotation": {"integrationId": self.news_sender.id, "integrationIds": []},
            "deleted": {"integrationIds": [deleted_id, self.updates_sender.id]},
            "legacy": "legacy@example.com",
            "legacy_named": "Acme Team <team@example.com>",
            "other_team": {"integrationId": foreign.id},
        }[sender]
        HogFlow.objects.create(team=self.team, name="Sender", actions=[_email("email_1", "Email", from_value)])

        (row,) = self._summaries().json()["results"]
        (step,) = row["email_steps"]
        ids = {
            "news": self.news_sender.id,
            "updates": self.updates_sender.id,
            "gone": deleted_id,
            "foreign": foreign.id,
        }
        assert (step["from_addresses"], step["from_name"], step["from_integration_ids"]) == (
            expected_addresses,
            expected_name,
            [ids[key] for key in expected_ids],
        )

    @parameterized.expand(
        [
            ("error", RuntimeError("metrics store unavailable")),
            ("timeout", ServerException("Timeout exceeded: elapsed 5 seconds", code=159)),
        ]
    )
    def test_totals_outage_returns_rows_without_totals(self, _name, error):
        self._mixed_flow()
        self.fetch_totals.side_effect = error

        response = self._summaries()
        assert response.status_code == 200, response.json()
        assert [row["last_7_days"] for row in response.json()["results"]] == [None]

    def test_workflow_without_metrics_gets_zero_totals(self):
        self._mixed_flow()
        self.fetch_totals.return_value = {"00000000-0000-0000-0000-000000000000": {"succeeded": 9, "failed": 9}}

        (row,) = self._summaries().json()["results"]
        assert row["last_7_days"] == {"succeeded": 0, "failed": 0}

    def test_totals_are_fetched_for_the_page_only_with_a_time_limit(self):
        oldest = HogFlow.objects.create(team=self.team, name="Flow 0")
        for index in range(1, 3):
            HogFlow.objects.create(team=self.team, name=f"Flow {index}")

        first_page = self._summaries("?limit=2").json()
        self._summaries("?limit=2&offset=5")

        assert self.fetch_totals.call_count == 1
        kwargs = self.fetch_totals.call_args.kwargs
        assert sorted(kwargs["app_source_ids"]) == sorted(row["id"] for row in first_page["results"])
        assert str(oldest.id) not in kwargs["app_source_ids"]
        assert 0 < kwargs["max_execution_time"] <= 10

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
        # An org admin skips object-level checks, so a per-row access query only shows for a member.
        member = User.objects.create_and_join(self.organization, "member@example.com", None)
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(team=self.team, resource="hog_flow", access_level="none")
        self.client.force_login(member)

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
                    access_level="viewer",
                    organization_member=membership,
                )
            with CaptureQueriesContext(connection) as queries:
                response = self._summaries()
            assert response.status_code == 200
            assert [row["user_access_level"] for row in response.json()["results"]] == ["viewer"] * rows
            (page_query,) = [
                query["sql"]
                for query in queries.captured_queries
                if query["sql"].startswith("SELECT")
                and 'FROM "posthog_hogflow"' in query["sql"]
                and " LIMIT " in query["sql"]
            ]
            selected = page_query.split(' FROM "posthog_hogflow"')[0]
            for column in ("draft", "draft_encrypted_inputs", "encrypted_inputs", "edges"):
                assert not re.search(rf'"posthog_hogflow"\."{column}"(,|$)', selected), column
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
        HogFlow.objects.filter(team=self.team).update(
            created_at=datetime(2026, 1, 1, tzinfo=UTC), updated_at=datetime(2026, 1, 1, tzinfo=UTC)
        )

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

    def test_saving_a_workflow_mid_load_neither_drops_nor_repeats_it(self):
        oldest = HogFlow.objects.create(team=self.team, name="Flow 0")
        for index in range(1, 3):
            HogFlow.objects.create(team=self.team, name=f"Flow {index}")

        page = self._summaries("?limit=2").json()
        seen = [row["id"] for row in page["results"]]
        oldest.name = "Renamed while loading"
        oldest.save()
        page = self.client.get(page["next"]).json()
        seen.extend(row["id"] for row in page["results"])

        assert page["next"] is None
        assert sorted(seen) == sorted(str(flow_id) for flow_id in HogFlow.objects.values_list("id", flat=True))

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


class TestHogFlowListRowSerializerContract(SimpleTestCase):
    @parameterized.expand(
        [
            ("without_the_page_sender_map", {}, {"has_draft": False}, KeyError),
            ("without_the_has_draft_annotation", {"email_sender_integrations": {}}, {}, AttributeError),
        ]
    )
    def test_a_row_serialized_outside_the_page_serializer_fails_loudly(self, _name, context, attributes, error):
        flow = HogFlow(team_id=1, name="Detached", actions=[_trigger()])
        for key, value in attributes.items():
            setattr(flow, key, value)

        with self.assertRaises(error):
            HogFlowListRowSerializer(flow, context=context).data  # noqa: B018
