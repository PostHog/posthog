from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.team.team_marketing_analytics_config import TeamMarketingAnalyticsConfig

from products.access_control.backend.models.access_control import AccessControl
from products.marketing_analytics.backend.services.conversion_goals_inspector import (
    ConversionGoalsListResponse,
    ConversionGoalSummary,
)

SCHEMA_MAP = {"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"}

_LIST_TARGET = "products.marketing_analytics.backend.api.list_conversion_goals"


def _summary_for(conversion_goal_id: str) -> ConversionGoalsListResponse:
    return ConversionGoalsListResponse(
        goals=[
            ConversionGoalSummary(
                conversion_goal_id=conversion_goal_id,
                name="Sign ups",
                kind="EventsNode",
                target_label="sign_up",
                last_30d_count=10,
                integrated_count=10,
                events_without_utm_source=0,
                events_with_unmatched_utm_source=0,
                non_integrated_count=0,
                integrated_pct=100.0,
                is_misconfigured=False,
                misconfig_reason=None,
            )
        ],
        attribution_window_days=90,
    )


def goal_payload(name: str, event: str = "sign_up", **extra) -> dict:
    return {"kind": "EventsNode", "event": event, "conversion_goal_name": name, "schema_map": SCHEMA_MAP, **extra}


class TestConversionGoalWrites(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/marketing_analytics/conversion_goals"
        # Writing goals needs the same project-admin level the settings PATCH path requires.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def create_goal(self, name: str, **extra):
        return self.client.post(f"{self.base_url}/create", {"goal": goal_payload(name, **extra)}, format="json")

    def stored_goals(self) -> list[dict]:
        return TeamMarketingAnalyticsConfig.objects.get(team=self.team).conversion_goals

    def test_create_appends_without_touching_existing_goals(self):
        first = self.create_goal("Sign ups").json()["goal"]
        response = self.create_goal("Purchases", event="purchase")

        assert response.status_code == 201, response.json()
        goals = self.stored_goals()
        assert [g["conversion_goal_name"] for g in goals] == ["Sign ups", "Purchases"]
        assert goals[0]["conversion_goal_id"] == first["conversion_goal_id"]

    def test_create_assigns_a_server_side_id_and_ignores_a_client_supplied_one(self):
        response = self.create_goal("Sign ups", conversion_goal_id="pick-me")

        assert response.json()["goal"]["conversion_goal_id"] != "pick-me"

    def test_update_merges_fields_and_keeps_position_and_siblings(self):
        first = self.create_goal("Sign ups").json()["goal"]
        self.create_goal("Purchases", event="purchase")

        response = self.client.patch(
            f"{self.base_url}/{first['conversion_goal_id']}/update",
            {"goal": {"kind": "EventsNode", "counts_as_customer": True}},
            format="json",
        )

        assert response.status_code == 200, response.json()
        goals = self.stored_goals()
        assert [g["conversion_goal_name"] for g in goals] == ["Sign ups", "Purchases"]
        assert goals[0]["counts_as_customer"] is True
        assert goals[0]["event"] == "sign_up"

    def test_update_does_not_report_the_goal_as_a_duplicate_of_itself(self):
        goal = self.create_goal("Sign ups").json()["goal"]

        response = self.client.patch(
            f"{self.base_url}/{goal['conversion_goal_id']}/update",
            {"goal": {"kind": "EventsNode", "conversion_goal_name": "Sign ups", "counts_as_revenue": False}},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_delete_removes_only_the_requested_goal(self):
        first = self.create_goal("Sign ups").json()["goal"]
        self.create_goal("Purchases", event="purchase")

        response = self.client.delete(f"{self.base_url}/{first['conversion_goal_id']}/delete")

        assert response.status_code == 200, response.json()
        assert [g["conversion_goal_name"] for g in self.stored_goals()] == ["Purchases"]

    @parameterized.expand([("update", "patch"), ("delete", "delete")])
    def test_unknown_goal_id_is_a_404(self, action: str, method: str):
        response = getattr(self.client, method)(f"{self.base_url}/nope/{action}", {"goal": {}}, format="json")

        assert response.status_code == 404, response.json()

    def test_member_without_project_admin_access_cannot_write_goals(self):
        existing = self.create_goal("Sign ups").json()["goal"]

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=self.team.id, access_level="member"
        )

        create = self.create_goal("Purchases", event="purchase")
        update = self.client.patch(
            f"{self.base_url}/{existing['conversion_goal_id']}/update",
            {"goal": {"kind": "EventsNode", "counts_as_customer": True}},
            format="json",
        )
        delete = self.client.delete(f"{self.base_url}/{existing['conversion_goal_id']}/delete")

        assert (create.status_code, update.status_code, delete.status_code) == (403, 403, 403)
        assert [g["conversion_goal_name"] for g in self.stored_goals()] == ["Sign ups"]
        # reads stay open to every member
        assert self.client.get(self.base_url).status_code == 200

    @parameterized.expand(
        [
            ("missing_schema_map", {"kind": "EventsNode", "event": "sign_up", "conversion_goal_name": "x"}),
            ("unknown_kind", {"kind": "NotANode", "conversion_goal_name": "x", "schema_map": SCHEMA_MAP}),
            ("schema_map_not_an_object", {"kind": "EventsNode", "conversion_goal_name": "x", "schema_map": "utm"}),
            (
                "wrong_field_type",
                {
                    "kind": "EventsNode",
                    "conversion_goal_name": "x",
                    "schema_map": SCHEMA_MAP,
                    "counts_as_customer": "maybe",
                },
            ),
            (
                "data_warehouse_node_without_table",
                {"kind": "DataWarehouseNode", "id": "x", "conversion_goal_name": "x", "schema_map": SCHEMA_MAP},
            ),
            ("goal_is_a_string", "sign_up"),
            ("goal_is_a_list", [{"kind": "EventsNode", "conversion_goal_name": "x", "schema_map": SCHEMA_MAP}]),
        ]
    )
    def test_malformed_goal_is_rejected(self, _name: str, goal: object):
        response = self.client.post(f"{self.base_url}/create", {"goal": goal}, format="json")

        assert response.status_code == 400, response.json()
        assert self.stored_goals() == []

    def test_duplicate_name_is_rejected(self):
        self.create_goal("Sign ups")

        response = self.create_goal("Sign ups", event="signed_up")

        assert response.status_code == 400, response.json()
        assert len(self.stored_goals()) == 1

    def test_a_malformed_stored_goal_does_not_block_writing_a_new_one(self):
        config = TeamMarketingAnalyticsConfig.objects.get(team=self.team)
        config._conversion_goals = ["not-a-goal"]
        config.save()

        response = self.create_goal("Sign ups")

        assert response.status_code == 201, response.json()
        assert [g["conversion_goal_name"] for g in self.stored_goals() if isinstance(g, dict)] == ["Sign ups"]

    @parameterized.expand([("trailing_space", "Sign ups "), ("different_case", "SIGN UPS")])
    def test_duplicate_name_is_rejected_ignoring_case_and_padding(self, _name: str, duplicate: str):
        # Goal names become SQL column aliases downstream, where these collide.
        self.create_goal("Sign ups")

        response = self.create_goal(duplicate, event="signed_up")

        assert response.status_code == 400, response.json()
        assert len(self.stored_goals()) == 1

    # --- the legacy full-config path ---
    #
    # The settings UI saves by PATCHing the whole marketing_analytics_config, which runs
    # `validate_conversion_goals`. That validator requires a top-level `name` the goal schema treats
    # as optional, so a goal written here without one makes every later UI save fail — and the UI
    # never exposes `name`, so there is no way to repair it from the product.

    def test_written_goals_carry_the_name_the_legacy_validator_requires(self):
        goal = self.create_goal("Sign ups").json()["goal"]

        assert goal["name"] == "Sign ups"
        assert self.stored_goals()[0]["name"] == "Sign ups"

    def test_renaming_keeps_the_legacy_name_in_step(self):
        goal = self.create_goal("Sign ups").json()["goal"]

        self.client.patch(
            f"{self.base_url}/{goal['conversion_goal_id']}/update",
            {"goal": {"conversion_goal_name": "Registrations"}},
            format="json",
        )

        stored = self.stored_goals()[0]
        assert (stored["conversion_goal_name"], stored["name"]) == ("Registrations", "Registrations")

    def test_goals_written_here_round_trip_through_the_settings_save(self):
        self.create_goal("Sign ups")
        self.create_goal("Purchases", event="purchase")

        # Exactly what marketingAnalyticsSettingsLogic sends on any settings change: the whole config.
        response = self.client.patch(
            f"/api/projects/{self.team.pk}/",
            {"marketing_analytics_config": {"conversion_goals": self.stored_goals()}},
            format="json",
        )

        assert response.status_code == 200, response.json()
        assert [g["conversion_goal_name"] for g in self.stored_goals()] == ["Sign ups", "Purchases"]

    # --- merge semantics ---

    def test_update_merges_schema_map_key_by_key(self):
        goal = self.create_goal("Sign ups").json()["goal"]

        response = self.client.patch(
            f"{self.base_url}/{goal['conversion_goal_id']}/update",
            {"goal": {"schema_map": {"utm_source_name": "source"}}},
            format="json",
        )

        assert response.status_code == 200, response.json()
        # Dropping utm_campaign_name here would leave the goal silently unreported: the query runner
        # falls back to a default column name and skips the goal with only a log warning.
        assert self.stored_goals()[0]["schema_map"] == {
            "utm_campaign_name": "utm_campaign",
            "utm_source_name": "source",
        }

    def test_update_can_change_a_goals_kind_by_replacing_it(self):
        goal = self.create_goal("Sign ups").json()["goal"]

        response = self.client.patch(
            f"{self.base_url}/{goal['conversion_goal_id']}/update",
            {
                "goal": {
                    "kind": "ActionsNode",
                    "id": "7",
                    "conversion_goal_name": "Sign ups",
                    "schema_map": SCHEMA_MAP,
                }
            },
            format="json",
        )

        assert response.status_code == 200, response.json()
        stored = self.stored_goals()[0]
        # Merging would have carried `event` over, which ActionsNode forbids — a 400 about a field
        # the client never sent.
        assert stored["kind"] == "ActionsNode"
        assert "event" not in stored
        assert stored["conversion_goal_id"] == goal["conversion_goal_id"]

    def test_error_message_describes_the_shape_that_was_sent(self):
        response = self.client.post(
            f"{self.base_url}/create",
            {"goal": {"kind": "DataWarehouseNode", "conversion_goal_name": "x", "schema_map": SCHEMA_MAP}},
            format="json",
        )

        assert response.status_code == 400, response.json()
        # Only the first message survives the exception handler, so it has to be the useful one: a
        # field the data warehouse shape actually needs, not the events node's objection to a `kind`
        # the client set deliberately.
        detail = response.json()["detail"]
        assert "'EventsNode'" not in detail, detail
        assert detail.split(":")[0] in {"id", "id_field", "distinct_id_field", "table_name", "timestamp_field"}, detail

    @parameterized.expand([("omitted", {}), ("null", {"goal": None})])
    def test_goal_is_required_on_update(self, _name: str, body: dict):
        goal = self.create_goal("Sign ups").json()["goal"]

        response = self.client.patch(f"{self.base_url}/{goal['conversion_goal_id']}/update", body, format="json")

        assert response.status_code == 400, response.json()
        assert self.stored_goals()[0]["conversion_goal_name"] == "Sign ups"

    @parameterized.expand([("update", "patch"), ("delete", "delete")])
    def test_a_rejected_write_leaves_the_stored_goals_untouched(self, action: str, method: str):
        first = self.create_goal("Sign ups").json()["goal"]
        self.create_goal("Purchases", event="purchase")
        before = self.stored_goals()

        if action == "update":
            # A merge that can't validate: counts_as_customer is a bool.
            response = self.client.patch(
                f"{self.base_url}/{first['conversion_goal_id']}/update",
                {"goal": {"counts_as_customer": "maybe"}},
                format="json",
            )
            assert response.status_code == 400, response.json()
        else:
            response = self.client.delete(f"{self.base_url}/does-not-exist/delete")
            assert response.status_code == 404, response.json()

        assert self.stored_goals() == before

    def test_another_teams_goals_are_not_reachable(self):
        goal = self.create_goal("Sign ups").json()["goal"]
        other_team = Team.objects.create(organization=self.organization, name="Other")

        other_url = f"/api/projects/{other_team.pk}/marketing_analytics/conversion_goals"
        update = self.client.patch(
            f"{other_url}/{goal['conversion_goal_id']}/update",
            {"goal": {"counts_as_customer": True}},
            format="json",
        )
        delete = self.client.delete(f"{other_url}/{goal['conversion_goal_id']}/delete")

        # The id belongs to this team's config, so the other project simply has no such goal.
        assert (update.status_code, delete.status_code) == (404, 404)
        assert "counts_as_customer" not in self.stored_goals()[0]

    def test_plain_member_cannot_write_goals_without_access_controls(self):
        """The endpoint must not be a way around the bar the settings page enforces.

        `marketing_analytics_config` sits in TEAM_CONFIG_ADMIN_FIELDS_SET, so the settings PATCH
        demands ADMIN. The RBAC check alone doesn't reproduce that: without the ACCESS_CONTROL
        feature it resolves permissively, and a plain member could edit goals here that the same
        member is refused on the settings page.
        """
        existing = self.create_goal("Sign ups").json()["goal"]
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        create = self.create_goal("Purchases", event="purchase")
        update = self.client.patch(
            f"{self.base_url}/{existing['conversion_goal_id']}/update",
            {"goal": {"counts_as_customer": True}},
            format="json",
        )
        delete = self.client.delete(f"{self.base_url}/{existing['conversion_goal_id']}/delete")
        # Same user, same payload, through the settings page the UI actually uses.
        legacy = self.client.patch(
            f"/api/projects/{self.team.pk}/",
            {"marketing_analytics_config": {"conversion_goals": []}},
            format="json",
        )

        assert (create.status_code, update.status_code, delete.status_code) == (403, 403, 403)
        assert legacy.status_code == 403, legacy.json()
        assert [g["conversion_goal_name"] for g in self.stored_goals()] == ["Sign ups"]
        assert self.client.get(self.base_url).status_code == 200

    def test_writes_leave_an_activity_log_trail(self):
        goal = self.create_goal("Sign ups").json()["goal"]
        self.client.patch(
            f"{self.base_url}/{goal['conversion_goal_id']}/update",
            {"goal": {"counts_as_customer": True}},
            format="json",
        )
        self.client.delete(f"{self.base_url}/{goal['conversion_goal_id']}/delete")

        # Without this, a goal changed by a person — or increasingly by an agent over MCP — leaves
        # no record of who changed what.
        entries = ActivityLog.objects.filter(team_id=self.team.pk, scope="Team", activity="updated")
        assert entries.count() == 3
        assert {entry.user_id for entry in entries} == {self.user.pk}


class TestConversionGoalIdIsOneName(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/marketing_analytics/conversion_goals"
        self.explain_url = f"/api/projects/{self.team.pk}/marketing_analytics/explain_conversion_goal"
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_the_list_calls_the_id_conversion_goal_id(self):
        goal = self.client.post(f"{self.base_url}/create", {"goal": goal_payload("Sign ups")}, format="json")
        created = goal.json()["goal"]

        listed = _summary_for(created["conversion_goal_id"])
        with patch(_LIST_TARGET, new=AsyncMock(return_value=listed)):
            response = self.client.get(self.base_url)

        assert response.status_code == 200, response.json()
        # The name every downstream endpoint asks for, so a caller can chain them.
        assert response.json()["goals"][0]["conversion_goal_id"] == created["conversion_goal_id"]

    def test_explain_takes_conversion_goal_id(self):
        response = self.client.get(self.explain_url, {"conversion_goal_id": "does-not-exist"})

        # 404 means the parameter was read and the lookup ran; 400 would mean it was never accepted.
        assert response.status_code == 404, response.status_code

    def test_explain_no_longer_answers_to_goal_id(self):
        response = self.client.get(self.explain_url, {"goal_id": "does-not-exist"})

        assert response.status_code == 400

    def test_update_and_delete_take_the_same_name(self):
        created = self.client.post(f"{self.base_url}/create", {"goal": goal_payload("Sign ups")}, format="json").json()[
            "goal"
        ]
        goal_id = created["conversion_goal_id"]

        update = self.client.patch(
            f"{self.base_url}/{goal_id}/update", {"goal": {"counts_as_customer": True}}, format="json"
        )
        delete = self.client.delete(f"{self.base_url}/{goal_id}/delete")

        assert (update.status_code, delete.status_code) == (200, 200), (update.json(), delete.json())
