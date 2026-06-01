from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.logs.backend.models import LogsExclusionRule


class TestLogsSamplingRulesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/logs/sampling_rules/"
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def _payload(self, **overrides):
        data = {
            "name": "Drop healthz",
            "rule_type": "path_drop",
            "config": {"patterns": ["/healthz"]},
            "scope_attribute_filters": [],
        }
        data.update(overrides)
        return data

    @patch("products.logs.backend.sampling_api.report_user_action")
    def test_create_defaults_disabled_and_priority(self, mock_report):
        response = self.client.post(self.base_url, self._payload(), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["enabled"] is False
        assert body["priority"] == 0
        assert body["version"] == 1
        mock_report.assert_called_once()

    def test_list_scoped_to_team(self):
        self.client.post(self.base_url, self._payload(name="r1"), format="json")
        other_team = self.create_team_with_organization(organization=self.organization)
        LogsExclusionRule.objects.create(
            team_id=other_team.id,
            name="other",
            enabled=False,
            priority=0,
            rule_type=LogsExclusionRule.RuleType.PATH_DROP,
            config={"patterns": []},
        )

        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == "r1"

    def test_reorder(self):
        a = self.client.post(self.base_url, self._payload(name="a"), format="json").json()
        b = self.client.post(self.base_url, self._payload(name="b"), format="json").json()

        reorder_url = f"{self.base_url}reorder/"
        r = self.client.post(reorder_url, {"ordered_ids": [b["id"], a["id"]]}, format="json")
        assert r.status_code == status.HTTP_200_OK, r.json()
        ordered = r.json()
        assert ordered[0]["id"] == b["id"]
        assert ordered[0]["priority"] == 0
        assert ordered[1]["id"] == a["id"]
        assert ordered[1]["priority"] == 1

    def test_create_rate_limit_requires_scope_service(self):
        response = self.client.post(
            self.base_url,
            self._payload(
                name="Cap api",
                rule_type="rate_limit",
                scope_service=None,
                config={"logs_per_second": 100},
            ),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "scope_service"

    def test_create_rate_limit_success(self):
        response = self.client.post(
            self.base_url,
            self._payload(
                name="Cap api",
                rule_type="rate_limit",
                scope_service="payment-api",
                config={"logs_per_second": 5000, "burst_logs": 15000},
            ),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["rule_type"] == "rate_limit"
        assert body["scope_service"] == "payment-api"
        assert body["config"]["logs_per_second"] == 5000
        assert body["config"]["burst_logs"] == 15000
