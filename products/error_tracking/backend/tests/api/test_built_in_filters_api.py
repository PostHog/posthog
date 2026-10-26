from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import call, patch

from rest_framework import status

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
        assert rule.built_in_version == BUILT_IN_FILTERS_BY_KEY["localhost"].version
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

    def test_turning_a_filter_on_again_retries_a_rule_that_ingestion_turned_off(self) -> None:
        self._set("legacy_browsers", True)
        ErrorTrackingSuppressionRule.objects.filter(team=self.team).update(
            disabled_data={"message": "Invalid regex", "props": {}}
        )

        listed = {f["key"]: f for f in self.client.get(self._url()).json()}
        assert listed["legacy_browsers"]["enabled"] is True
        assert listed["legacy_browsers"]["disabled_reason"] == "Invalid regex"

        assert self._set("legacy_browsers", True)["disabled_reason"] is None
        assert ErrorTrackingSuppressionRule.objects.get(team=self.team).disabled_data is None

    def test_unknown_filter_returns_404(self) -> None:
        response = self.client.patch(self._url("not_a_filter"), data={"enabled": True}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestRefreshStaleBuiltInFilterRules(BaseTest):
    def test_refresh_upgrades_only_rules_older_than_their_definition(self) -> None:
        definition = BUILT_IN_FILTERS_BY_KEY["localhost"]
        set_built_in_filter_enabled(self.team.id, "chunk_load_errors", enabled=True)
        stale = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters={"type": "OR", "values": []},
            bytecode=[],
            order_key=0,
            built_in_key="localhost",
            built_in_version=definition.version - 1,
            disabled_data={"message": "Invalid regex", "props": {}},
        )
        newer = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters={"type": "OR", "values": []},
            bytecode=[],
            order_key=0,
            built_in_key="web_crawlers",
            built_in_version=BUILT_IN_FILTERS_BY_KEY["web_crawlers"].version + 1,
        )
        unknown = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters={"type": "OR", "values": []},
            bytecode=[],
            order_key=0,
            built_in_key="retired_filter",
            built_in_version=1,
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
        assert stale.built_in_version == definition.version
        assert stale.disabled_data is None
        assert {
            rule.id: rule.updated_at
            for rule in ErrorTrackingSuppressionRule.objects.filter(team=self.team).exclude(id=stale.id)
        } == untouched
        assert {newer.id, unknown.id} <= untouched.keys()
