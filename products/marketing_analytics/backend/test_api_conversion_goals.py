from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team_marketing_analytics_config import TeamMarketingAnalyticsConfig

from ee.models.rbac.access_control import AccessControl

SCHEMA_MAP = {"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"}


def goal_payload(name: str, event: str = "sign_up", **extra) -> dict:
    return {"kind": "EventsNode", "event": event, "conversion_goal_name": name, "schema_map": SCHEMA_MAP, **extra}


class TestConversionGoalWrites(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/marketing_analytics/conversion_goals"

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
