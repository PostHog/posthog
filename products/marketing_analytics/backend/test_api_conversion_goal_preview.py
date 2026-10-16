from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Team, TeamMarketingAnalyticsConfig
from posthog.models.organization import OrganizationMembership
from posthog.test.persons import create_person

from products.access_control.backend.models.access_control import AccessControl
from products.actions.backend.models.action import Action
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.marketing_analytics.backend.api import ConversionGoalPreviewSerializer


def preview_payload() -> dict:
    return {
        "goal": {
            "kind": "EventsNode",
            "event": "purchase",
            "conversion_goal_name": "Paid purchases",
            "schema_map": {},
            "math": "sum",
            "math_property": "amount",
            "counts_as_revenue": True,
        },
        "date_from": "2023-01-01T00:00:00Z",
        "date_to": "2023-01-31T23:59:59Z",
        "filter_test_accounts": False,
    }


class TestConversionGoalPreviewValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("period", {"date_to": "2023-03-01T00:00:00Z"}, {}),
            ("reversed", {"date_to": "2022-12-31T00:00:00Z"}, {}),
            ("zero", {"date_to": "2023-01-01T00:00:00Z"}, {}),
            ("missing_amount", {}, {"math_property": None}),
            ("revenue_count", {}, {"math": "total"}),
            ("unsupported_math", {}, {"math": "avg", "counts_as_revenue": False}),
            ("multiplier", {}, {"math_multiplier": 0.01}),
            ("group", {}, {"math_group_type_index": 0}),
            ("lookback", {"lookback_window_days": 10000}, {}),
        ]
    )
    def test_rejects_unsupported_or_unbounded_preview(self, _name: str, changes: dict, goal_changes: dict) -> None:
        payload = preview_payload()
        payload.update(changes)
        payload["goal"].update(goal_changes)
        serializer = ConversionGoalPreviewSerializer(data=payload)
        assert not serializer.is_valid()


class TestConversionGoalPreviewAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.pk}/marketing_analytics/conversion_goals/preview"
        self.flag = patch("products.marketing_analytics.backend.api.feature_enabled_or_false", return_value=True)
        self.flag.start()
        self.addCleanup(self.flag.stop)

    def test_member_can_preview_without_saving_or_reading_other_projects(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        assert not TeamMarketingAnalyticsConfig.objects.filter(team=self.team).exists()
        create_person(team=self.team, distinct_ids=["buyer"])
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="buyer",
            timestamp="2023-01-10T12:00:00Z",
            properties={"amount": 125.5},
        )
        other = Team.objects.create(organization=self.organization)
        create_person(team=other, distinct_ids=["buyer"])
        _create_event(
            team=other,
            event="purchase",
            distinct_id="buyer",
            timestamp="2023-01-10T12:00:00Z",
            properties={"amount": 999.0},
        )
        flush_persons_and_events()

        response = self.client.post(self.url, preview_payload(), format="json")

        assert response.status_code == 200, response.json()
        result = response.json()
        assert result["preview_ref"]
        assert result["total_conversions"] == 1
        assert result["total_value"] == 125.5
        assert result["unattributed_value"] == 125.5
        assert result["currency"] == "USD"
        assert result["is_approximate"] is False
        assert "business_definition_validation" in result["checks_not_performed"]
        assert "transaction_uniqueness" in result["checks_not_performed"]
        assert "first_ever_customer_validation" in result["checks_not_performed"]
        assert any("do not deduplicate" in warning for warning in result["warnings"])
        assert datetime.fromisoformat(result["date_to"].replace("Z", "+00:00")) == datetime(
            2023, 1, 31, 23, 59, 59, tzinfo=UTC
        )
        config = TeamMarketingAnalyticsConfig.objects.get(team=self.team)
        assert config.conversion_goals == []

    def test_rejects_a_foreign_action(self) -> None:
        other = Team.objects.create(organization=self.organization)
        action = Action.objects.create(team=other, name="Foreign purchase", steps_json=[{"event": "purchase"}])
        payload = preview_payload()
        payload["goal"].pop("event")
        payload["goal"].update(kind="ActionsNode", id=str(action.pk))
        response = self.client.post(self.url, payload, format="json")
        assert response.status_code == 400, response.json()

    def test_cannot_preview_a_restricted_warehouse_view(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="none")
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="restricted_payments",
            query={
                "kind": "HogQLQuery",
                "query": "SELECT uuid AS id, timestamp, distinct_id, 10 AS amount FROM events",
            },
            columns={"id": "String", "timestamp": "DateTime", "distinct_id": "String", "amount": "Float64"},
        )
        payload = preview_payload()
        payload["goal"].pop("event")
        payload["goal"].update(
            kind="DataWarehouseNode",
            id=str(view.id),
            table_name=view.name,
            id_field="id",
            timestamp_field="timestamp",
            distinct_id_field="distinct_id",
        )
        with patch(
            "posthog.hogql.database.database.feature_enabled_or_false",
            side_effect=lambda key, *args, **kwargs: key == "hogql-warehouse-access-control",
        ):
            response = self.client.post(self.url, payload, format="json")
        assert response.status_code == 403, response.json()

    def test_rejects_an_unbounded_period(self) -> None:
        payload = preview_payload()
        payload["date_to"] = "2024-01-01T00:00:00Z"
        response = self.client.post(self.url, payload, format="json")
        assert response.status_code == 400, response.json()

    @parameterized.expand(
        [
            ("all_disabled", set()),
            ("setup_only", {"marketing-analytics-setup"}),
            ("dashboard_only", {"new-marketing-analytics-dashboard"}),
            ("ai_only", {"marketing-analytics-conversion-setup-ai"}),
        ]
    )
    def test_requires_setup_and_ai_features(self, _name: str, enabled_flags: set[str]) -> None:
        with (
            patch(
                "products.marketing_analytics.backend.api.feature_enabled_or_false",
                side_effect=lambda flag, *args, **kwargs: flag in enabled_flags,
            ),
            patch("products.marketing_analytics.backend.api.ConversionGoalPreviewRunner") as runner,
        ):
            response = self.client.post(self.url, preview_payload(), format="json")
        assert response.status_code == 404, response.json()
        runner.assert_not_called()
