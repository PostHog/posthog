from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.scoping import team_scope

from products.logs.backend.models import MAX_ENABLED_METRIC_RULES, LogsMetricRule
from products.logs.backend.presentation.views.metric_rules_api import LogsMetricRuleSerializer

VALID_FILTER_GROUP = {
    "type": "AND",
    "values": [
        {
            "type": "AND",
            "values": [{"key": "service.name", "operator": "exact", "value": "api", "type": "log_attribute"}],
        }
    ],
}


class TestLogsMetricRuleSerializerValidation(SimpleTestCase):
    def _serializer(self, **overrides):
        data = {
            "name": "API errors",
            "metric_name": "log.api_errors",
            "filter_group": VALID_FILTER_GROUP,
        }
        data.update(overrides)
        return LogsMetricRuleSerializer(data=data)

    @parameterized.expand(
        [
            ("starts_with_digit", "1metric"),
            ("starts_with_dot", ".metric"),
            ("contains_space", "log errors"),
            ("contains_slash", "log/errors"),
            ("empty", ""),
        ]
    )
    def test_rejects_invalid_metric_name(self, _label, metric_name):
        s = self._serializer(metric_name=metric_name)
        assert not s.is_valid()
        assert "metric_name" in s.errors

    @parameterized.expand(
        [
            ("simple", "log_errors"),
            ("dotted", "log.api.errors"),
            ("dashed", "log-errors"),
            ("mixed", "Log.API_errors-2"),
        ]
    )
    def test_accepts_valid_metric_name(self, _label, metric_name):
        s = self._serializer(metric_name=metric_name)
        assert s.is_valid(), s.errors

    def test_rejects_more_than_five_group_by_keys(self):
        s = self._serializer(group_by=[f"attributes.k{i}" for i in range(6)])
        assert not s.is_valid()
        assert "group_by" in s.errors

    @parameterized.expand(
        [
            ("unknown_top_level", ["severity_number"]),
            ("body", ["body"]),
            ("bare_prefix", ["attributes."]),
            ("unprefixed_attribute", ["http.status_code"]),
        ]
    )
    def test_rejects_invalid_group_by_key(self, _label, group_by):
        s = self._serializer(group_by=group_by)
        assert not s.is_valid()
        assert "group_by" in s.errors

    def test_accepts_valid_group_by_keys(self):
        s = self._serializer(
            group_by=["service_name", "severity_text", "attributes.http.status_code", "resource_attributes.k8s.pod"]
        )
        assert s.is_valid(), s.errors

    def test_count_rule_without_value_attribute_is_valid(self):
        s = self._serializer()
        assert s.is_valid(), s.errors
        assert s.validated_data.get("value_attribute") is None

    def test_null_filter_group_matches_all_logs(self):
        s = self._serializer(filter_group=None)
        assert s.is_valid(), s.errors

    @parameterized.expand(
        [
            ("not_a_group", {"key": "service.name"}),
            ("list_shape", [{"type": "AND", "values": []}]),
            ("vacuous_group", {"type": "AND", "values": []}),
        ]
    )
    def test_rejects_malformed_filter_group(self, _label, filter_group):
        s = self._serializer(filter_group=filter_group)
        assert not s.is_valid()
        assert "filter_group" in s.errors

    def test_rejects_too_deep_filter_group(self):
        node: dict = {
            "type": "AND",
            "values": [{"key": "service.name", "operator": "exact", "value": "api", "type": "log_attribute"}],
        }
        for _ in range(20):
            node = {"type": "AND", "values": [node]}
        s = self._serializer(filter_group=node)
        assert not s.is_valid()
        assert "filter_group" in s.errors


class TestLogsMetricRulesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/logs/metric_rules/"
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def _payload(self, **overrides):
        data = {
            "name": "API errors",
            "metric_name": "log.api_errors",
            "filter_group": VALID_FILTER_GROUP,
        }
        data.update(overrides)
        return data

    @patch("products.logs.backend.presentation.views.metric_rules_api.report_user_action")
    def test_create_defaults(self, mock_report):
        response = self.client.post(self.base_url, self._payload(), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["enabled"] is False
        assert body["version"] == 1
        assert body["value_attribute"] is None
        assert body["group_by"] == []
        mock_report.assert_called_once()

    def test_list_scoped_to_team(self):
        self.client.post(self.base_url, self._payload(), format="json")
        other_team = self.create_team_with_organization(organization=self.organization)
        with team_scope(other_team.id):
            LogsMetricRule.objects.create(team=other_team, name="other", metric_name="other.metric")

        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["metric_name"] == "log.api_errors"

    def test_create_attribute_rule(self):
        response = self.client.post(
            self.base_url,
            self._payload(metric_name="log.request_duration", value_attribute="attributes.duration_ms"),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["value_attribute"] == "attributes.duration_ms"

    def test_rejects_duplicate_metric_name_for_team(self):
        assert self.client.post(self.base_url, self._payload(), format="json").status_code == status.HTTP_201_CREATED
        response = self.client.post(self.base_url, self._payload(name="Another"), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_rejects_enabling_more_than_max_rules(self):
        for i in range(MAX_ENABLED_METRIC_RULES):
            r = self.client.post(
                self.base_url,
                self._payload(name=f"r{i}", metric_name=f"log.m{i}", enabled=True),
                format="json",
            )
            assert r.status_code == status.HTTP_201_CREATED, r.json()
        response = self.client.post(
            self.base_url, self._payload(name="overflow", metric_name="log.overflow", enabled=True), format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        # Disabled rules are not capped.
        response = self.client.post(
            self.base_url, self._payload(name="disabled", metric_name="log.disabled", enabled=False), format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

    def test_metric_name_and_value_attribute_immutable_on_update(self):
        created = self.client.post(self.base_url, self._payload(), format="json").json()
        detail_url = f"{self.base_url}{created['id']}/"

        response = self.client.patch(detail_url, {"metric_name": "log.renamed"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

        response = self.client.patch(detail_url, {"value_attribute": "attributes.duration_ms"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_update_filter_and_group_by_bumps_version(self):
        created = self.client.post(self.base_url, self._payload(), format="json").json()
        detail_url = f"{self.base_url}{created['id']}/"

        response = self.client.patch(detail_url, {"group_by": ["severity_text"], "enabled": True}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["group_by"] == ["severity_text"]
        assert body["enabled"] is True
        assert body["version"] == created["version"] + 1

    def test_requires_feature_flag(self):
        self._ff_patcher.stop()
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = self.client.post(self.base_url, self._payload(), format="json")
            assert response.status_code == status.HTTP_403_FORBIDDEN
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
