from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from products.logs.backend.models import LogsRetentionRule
from products.logs.backend.presentation.views.retention_api import LogsRetentionRuleViewSet

VALID_FILTER_GROUP = {"type": "AND", "values": [{"type": "AND", "values": []}]}


class TestLogsRetentionRulesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/logs/retention_rules/"
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def _grant_30d_retention(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.LOGS_RETENTION_30D, "name": AvailableFeature.LOGS_RETENTION_30D}
        ]
        self.organization.save()

    def _payload(self, **overrides):
        # 14 days is the always-available free tier, so the generic CRUD tests need no entitlement.
        data = {
            "name": "Keep api logs longer",
            "config": {"retention_days": 14, "filter_group": VALID_FILTER_GROUP},
        }
        data.update(overrides)
        return data

    @patch("products.logs.backend.presentation.views.retention_api.report_user_action")
    def test_create_defaults_disabled_and_priority(self, mock_report):
        response = self.client.post(self.base_url, self._payload(), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["enabled"] is False
        assert body["priority"] == 0
        assert body["version"] == 1
        assert body["config"]["retention_days"] == 14
        mock_report.assert_called_once()

    def test_paid_tier_requires_org_entitlement(self):
        # 30 days is entitlement-gated; without the feature the org can't set it via a rule either.
        denied = self.client.post(
            self.base_url,
            self._payload(config={"retention_days": 30, "filter_group": VALID_FILTER_GROUP}),
            format="json",
        )
        assert denied.status_code == status.HTTP_403_FORBIDDEN, denied.json()
        assert LogsRetentionRule.objects.count() == 0

        self._grant_30d_retention()
        allowed = self.client.post(
            self.base_url,
            self._payload(config={"retention_days": 30, "filter_group": VALID_FILTER_GROUP}),
            format="json",
        )
        assert allowed.status_code == status.HTTP_201_CREATED, allowed.json()
        assert allowed.json()["config"]["retention_days"] == 30

    def test_list_scoped_to_team(self):
        self.client.post(self.base_url, self._payload(name="mine"), format="json")
        other_team = self.create_team_with_organization(organization=self.organization)
        LogsRetentionRule.objects.create(
            team_id=other_team.id,
            name="other",
            enabled=False,
            priority=0,
            config={"retention_days": 30, "filter_group": VALID_FILTER_GROUP},
        )

        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == "mine"

    def test_reorder(self):
        a = self.client.post(self.base_url, self._payload(name="a"), format="json").json()
        b = self.client.post(self.base_url, self._payload(name="b"), format="json").json()

        r = self.client.post(f"{self.base_url}reorder/", {"ordered_ids": [b["id"], a["id"]]}, format="json")
        assert r.status_code == status.HTTP_200_OK, r.json()
        ordered = r.json()
        assert ordered[0]["id"] == b["id"] and ordered[0]["priority"] == 0
        assert ordered[1]["id"] == a["id"] and ordered[1]["priority"] == 1

    def test_append_priority_when_existing_max_is_zero(self):
        first = self.client.post(self.base_url, self._payload(name="first"), format="json").json()
        assert first["priority"] == 0
        second = self.client.post(self.base_url, self._payload(name="second"), format="json").json()
        # Guards the `max or -1` footgun: max priority 0 is falsy, so a second rule must still
        # append at 1 rather than collide at 0.
        assert second["priority"] == 1

    def test_update_with_null_priority_does_not_error(self):
        rule = self.client.post(self.base_url, self._payload(name="r"), format="json").json()
        response = self.client.patch(
            f"{self.base_url}{rule['id']}/",
            {"name": "renamed", "priority": None},
            format="json",
        )
        # A null priority must not reach the non-nullable column (would 500); the stored value stays.
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["priority"] == 0

    @parameterized.expand(
        [
            ("non_tier_value", {"retention_days": 45, "filter_group": VALID_FILTER_GROUP}),
            ("ninety_no_longer_a_tier", {"retention_days": 90, "filter_group": VALID_FILTER_GROUP}),
            ("boolean_masquerading_as_int", {"retention_days": True, "filter_group": VALID_FILTER_GROUP}),
            ("missing_retention_days", {"filter_group": VALID_FILTER_GROUP}),
            ("missing_filter_group", {"retention_days": 14}),
            ("malformed_filter_group", {"retention_days": 14, "filter_group": ["not", "an", "object"]}),
            (
                "oversized_leaf_value",
                {
                    "retention_days": 14,
                    "filter_group": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "service.name",
                                        "type": "log_resource_attribute",
                                        "operator": "exact",
                                        "value": "x" * 2000,
                                    }
                                ],
                            }
                        ],
                    },
                },
            ),
        ]
    )
    def test_invalid_config_rejected(self, _name, config):
        response = self.client.post(self.base_url, self._payload(config=config), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert LogsRetentionRule.objects.count() == 0


class TestLogsRetentionRuleSuggestName(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.pk}/logs/retention_rules/suggest_name/"
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def test_returns_generated_name(self):
        with patch(
            "products.logs.backend.presentation.views.retention_api.suggest_retention_rule_name",
            return_value="Keep api logs for 14 days",
        ) as mock_suggest:
            response = self.client.post(
                self.url, {"retention_days": 14, "filter_group": VALID_FILTER_GROUP}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"name": "Keep api logs for 14 days"}
        assert mock_suggest.call_args.args == (14, VALID_FILTER_GROUP)
        assert mock_suggest.call_args.kwargs["team_id"] == self.team.pk

    def test_requires_ai_data_processing_approval(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        with patch(
            "products.logs.backend.presentation.views.retention_api.suggest_retention_rule_name"
        ) as mock_suggest:
            response = self.client.post(
                self.url, {"retention_days": 14, "filter_group": VALID_FILTER_GROUP}, format="json"
            )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        mock_suggest.assert_not_called()

    def test_rejects_invalid_retention_days(self):
        with patch(
            "products.logs.backend.presentation.views.retention_api.suggest_retention_rule_name"
        ) as mock_suggest:
            response = self.client.post(
                self.url, {"retention_days": 45, "filter_group": VALID_FILTER_GROUP}, format="json"
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        mock_suggest.assert_not_called()

    def test_rejects_oversized_filter_group(self):
        # Proves the endpoint reuses the same bounds as a write, so an unbounded tree never reaches
        # the LLM prompt.
        oversized = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "service.name",
                            "type": "log_resource_attribute",
                            "operator": "exact",
                            "value": "x" * 2000,
                        }
                    ],
                }
            ],
        }
        with patch(
            "products.logs.backend.presentation.views.retention_api.suggest_retention_rule_name"
        ) as mock_suggest:
            response = self.client.post(self.url, {"retention_days": 14, "filter_group": oversized}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        mock_suggest.assert_not_called()

    def test_returns_blank_name_when_generation_fails(self):
        with patch(
            "products.logs.backend.presentation.views.retention_api.suggest_retention_rule_name",
            return_value="",
        ):
            response = self.client.post(
                self.url, {"retention_days": 14, "filter_group": VALID_FILTER_GROUP}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"name": ""}

    def test_paid_tier_does_not_require_entitlement(self):
        # Naming a rule isn't granting it — the entitlement check belongs on the write, not the hint.
        with patch(
            "products.logs.backend.presentation.views.retention_api.suggest_retention_rule_name",
            return_value="Keep api logs for 30 days",
        ):
            response = self.client.post(
                self.url, {"retention_days": 30, "filter_group": VALID_FILTER_GROUP}, format="json"
            )
        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_takes_the_shared_ai_throttles(self):
        assert LogsRetentionRuleViewSet.suggest_name.kwargs["throttle_classes"] == [
            AIBurstRateThrottle,
            AISustainedRateThrottle,
        ]
