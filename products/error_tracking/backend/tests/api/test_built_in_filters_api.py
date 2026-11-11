import pytest
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import call, patch

from parameterized import parameterized
from rest_framework import status
from temporalio.exceptions import CancelledError

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.facade.testing import create_access_control
from products.error_tracking.backend.logic.built_in_filter_definitions import BUILT_IN_FILTERS_BY_KEY
from products.error_tracking.backend.logic.built_in_filters import (
    refresh_stale_built_in_filter_rules,
    set_built_in_filter_enabled,
)
from products.error_tracking.backend.logic.rules import get_client_safe_suppression_rules
from products.error_tracking.backend.models import ErrorTrackingSuppressionRule


class TestBuiltInFiltersAPI(APIBaseTest):
    def _url(self, key: str | None = None) -> str:
        base = f"/api/projects/{self.team.id}/error_tracking/built_in_filters/"
        return f"{base}{key}/" if key else base

    def _set(self, key: str, enabled: bool) -> dict:
        response = self.client.patch(self._url(key), data={"enabled": enabled}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _enabled_keys(self) -> set[str]:
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        return {f["key"] for f in response.json() if f["enabled"]}

    def test_toggling_a_filter_creates_and_deletes_one_rule(self) -> None:
        assert self._enabled_keys() == set()

        self._set("localhost", True)
        self._set("localhost", True)

        rule = ErrorTrackingSuppressionRule.objects.get(team=self.team)
        assert rule.built_in_key == "localhost"
        assert rule.built_in_hash == BUILT_IN_FILTERS_BY_KEY["localhost"].filters_hash
        assert rule.bytecode
        assert self._enabled_keys() == {"localhost"}

        self._set("localhost", False)
        self._set("localhost", False)

        assert not ErrorTrackingSuppressionRule.objects.filter(team=self.team).exists()
        assert self._enabled_keys() == set()

    def test_only_client_filters_reach_the_sdk_config(self) -> None:
        for key in BUILT_IN_FILTERS_BY_KEY:
            self._set(key, True)

        response = self.client.get(self._url())
        evaluation = {f["key"]: f["evaluation"] for f in response.json()}
        assert evaluation == {
            "web_crawlers": "server",
            "localhost": "server",
            "legacy_browsers": "server",
            "react_hydration_errors": "client",
            "chunk_load_errors": "client",
            "resize_observer_loop": "client",
        }
        sdk_rules = get_client_safe_suppression_rules(self.team.id)
        client_keys = [key for key, where in evaluation.items() if where == "client"]
        assert len(sdk_rules) == len(client_keys)
        assert all(BUILT_IN_FILTERS_BY_KEY[key].filters in sdk_rules for key in client_keys)

    def test_turning_a_filter_off_rebuilds_the_sdk_config(self) -> None:
        self._set("resize_observer_loop", True)

        with patch("posthog.models.remote_config._update_team_remote_config") as mock_rebuild:
            with self.captureOnCommitCallbacks(execute=True):
                self._set("resize_observer_loop", False)

        assert mock_rebuild.call_args_list == [call(self.team.id)]

    def test_custom_rule_endpoints_cannot_see_or_change_built_in_rules(self) -> None:
        self._set("web_crawlers", True)
        rule = ErrorTrackingSuppressionRule.objects.get(team=self.team)
        rules_url = f"/api/projects/{self.team.id}/error_tracking/suppression_rules/"

        assert self.client.get(rules_url).json()["results"] == []
        assert self.client.get(f"{rules_url}{rule.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert (
            self.client.patch(f"{rules_url}{rule.id}/", data={"sampling_rate": 0.5}, format="json").status_code
            == status.HTTP_404_NOT_FOUND
        )
        assert self.client.delete(f"{rules_url}{rule.id}/").status_code == status.HTTP_404_NOT_FOUND
        self.client.patch(f"{rules_url}reorder/", data={"orders": {str(rule.id): 5}}, format="json")

        rule.refresh_from_db()
        assert rule.sampling_rate == 1.0
        assert rule.order_key == 0

    @parameterized.expand([("current_definition", False), ("changed_definition", True)])
    def test_turning_a_filter_on_again_retries_a_rule_that_ingestion_turned_off(
        self, _name: str, definition_changed: bool
    ) -> None:
        definition = BUILT_IN_FILTERS_BY_KEY["legacy_browsers"]
        self._set("legacy_browsers", True)
        ErrorTrackingSuppressionRule.objects.filter(team=self.team).update(
            disabled_data={"message": "Invalid regex", "props": {}},
            **({"filters": {"type": "OR", "values": []}, "built_in_hash": "stale"} if definition_changed else {}),
        )

        listed = {f["key"]: f for f in self.client.get(self._url()).json()}
        assert listed["legacy_browsers"]["enabled"] is True
        assert listed["legacy_browsers"]["disabled_reason"] == "Invalid regex"

        assert self._set("legacy_browsers", True)["disabled_reason"] is None
        rule = ErrorTrackingSuppressionRule.objects.get(team=self.team)
        assert rule.disabled_data is None
        assert rule.filters == definition.filters
        assert rule.built_in_hash == definition.filters_hash

    @pytest.mark.ee
    def test_toggling_requires_resource_level_access(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        restricted_user = User.objects.create_and_join(self.organization, "restricted@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=restricted_user, organization=self.organization)
        create_access_control(team_id=self.team.id, resource="error_tracking", access_level="none")
        create_access_control(
            team_id=self.team.id,
            resource="error_tracking",
            resource_id="00000000-0000-0000-0000-000000000001",
            access_level="editor",
            organization_member_id=membership.id,
        )
        self.client.force_login(restricted_user)

        response = self.client.patch(self._url("web_crawlers"), data={"enabled": True}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not ErrorTrackingSuppressionRule.objects.filter(team=self.team).exists()

    def test_unknown_filter_returns_404(self) -> None:
        response = self.client.patch(self._url("not_a_filter"), data={"enabled": True}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestRefreshStaleBuiltInFilterRules(BaseTest):
    def test_refresh_rewrites_only_rules_whose_definition_changed(self) -> None:
        definition = BUILT_IN_FILTERS_BY_KEY["localhost"]
        set_built_in_filter_enabled(self.team.id, "chunk_load_errors", enabled=True)
        stale = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters={"type": "OR", "values": []},
            bytecode=[],
            order_key=0,
            built_in_key="localhost",
            built_in_hash="stale",
            disabled_data={"message": "Invalid regex", "props": {}},
        )
        unknown = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters={"type": "OR", "values": []},
            bytecode=[],
            order_key=0,
            built_in_key="retired_filter",
            built_in_hash="stale",
        )
        untouched = {
            rule.id: rule.updated_at
            for rule in ErrorTrackingSuppressionRule.objects.filter(team=self.team).exclude(id=stale.id)
        }

        result = refresh_stale_built_in_filter_rules(batch_size=1)

        assert (result.rules_refreshed, result.rules_failed) == (1, 0)
        stale.refresh_from_db()
        assert stale.filters == definition.filters
        assert stale.bytecode
        assert stale.built_in_hash == definition.filters_hash
        assert stale.disabled_data is None
        assert {
            rule.id: rule.updated_at
            for rule in ErrorTrackingSuppressionRule.objects.filter(team=self.team).exclude(id=stale.id)
        } == untouched
        assert unknown.id in untouched

    def test_refresh_stops_when_temporal_cancels_it(self) -> None:
        for key in ("localhost", "legacy_browsers"):
            ErrorTrackingSuppressionRule.objects.create(
                team=self.team,
                filters={"type": "OR", "values": []},
                bytecode=[],
                order_key=0,
                built_in_key=key,
                built_in_hash="stale",
            )

        with (
            patch(
                "products.error_tracking.backend.logic.built_in_filters.compile_filter_bytecode",
                side_effect=CancelledError("cancelled"),
            ) as compile_bytecode,
            pytest.raises(CancelledError),
        ):
            refresh_stale_built_in_filter_rules(batch_size=1)

        assert compile_bytecode.call_count == 1
