from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.constants import AvailableFeature

from products.logs.backend.models import LogsRetentionRule
from products.tracing.backend.models import TracesRetentionRule

VALID_FILTER_GROUP = {"type": "AND", "values": [{"type": "AND", "values": []}]}


class TestTracingRetentionRulesAPI(APIBaseTest):
    """Span retention rules share the logs implementation over their own model, so these cover
    that every path of the shared viewset reaches the span model and never the log one."""

    def setUp(self):
        super().setUp()
        self.spans_url = f"/api/projects/{self.team.pk}/tracing/retention_rules/"
        self.logs_url = f"/api/projects/{self.team.pk}/logs/retention_rules/"
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def _payload(self, name="Keep checkout spans longer", **overrides):
        data = {
            "name": name,
            "config": {"retention_days": 14, "filter_group": VALID_FILTER_GROUP},
        }
        data.update(overrides)
        return data

    def _create_span_rule(self, name="Keep checkout spans longer"):
        response = self.client.post(self.spans_url, self._payload(name), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def test_create_stores_a_span_rule(self):
        body = self._create_span_rule()
        assert TracesRetentionRule.objects.for_team(self.team.pk).filter(id=body["id"]).exists()
        assert not LogsRetentionRule.objects.filter(id=body["id"]).exists()

    def test_each_source_only_lists_its_own_rules(self):
        span_rule = self._create_span_rule()
        log_response = self.client.post(self.logs_url, self._payload("Keep api logs longer"), format="json")
        assert log_response.status_code == status.HTTP_201_CREATED, log_response.json()
        log_rule = log_response.json()

        span_ids = [r["id"] for r in self.client.get(self.spans_url).json()["results"]]
        log_ids = [r["id"] for r in self.client.get(self.logs_url).json()["results"]]
        assert span_ids == [span_rule["id"]]
        assert log_ids == [log_rule["id"]]

    def test_a_rule_of_the_other_source_is_not_reachable(self):
        log_response = self.client.post(self.logs_url, self._payload("Keep api logs longer"), format="json")
        log_rule_id = log_response.json()["id"]
        assert self.client.get(f"{self.spans_url}{log_rule_id}/").status_code == status.HTTP_404_NOT_FOUND

    def test_priorities_are_numbered_per_source(self):
        # Both rules are the first of their source, so both start at priority 0.
        first_span = self._create_span_rule("First span rule")
        log_rule = self.client.post(self.logs_url, self._payload("First log rule"), format="json").json()
        second_span = self._create_span_rule("Second span rule")
        assert first_span["priority"] == 0
        assert log_rule["priority"] == 0
        assert second_span["priority"] == 1

    def test_reorder_only_covers_the_routes_own_source(self):
        first = self._create_span_rule("First span rule")
        second = self._create_span_rule("Second span rule")
        log_rule = self.client.post(self.logs_url, self._payload("A log rule"), format="json").json()

        # Listing the log rule as well must be refused — it belongs to the other source.
        mixed = self.client.post(
            f"{self.spans_url}reorder/",
            {"ordered_ids": [second["id"], first["id"], log_rule["id"]]},
            format="json",
        )
        assert mixed.status_code == status.HTTP_400_BAD_REQUEST

        reordered = self.client.post(
            f"{self.spans_url}reorder/",
            {"ordered_ids": [second["id"], first["id"]]},
            format="json",
        )
        assert reordered.status_code == status.HTTP_200_OK, reordered.json()
        assert [r["id"] for r in reordered.json()] == [second["id"], first["id"]]
        # The log rule keeps its own priority.
        assert LogsRetentionRule.objects.get(id=log_rule["id"]).priority == 0

    def test_paid_tier_requires_the_same_org_entitlement_as_logs(self):
        denied = self.client.post(
            self.spans_url,
            self._payload(config={"retention_days": 30, "filter_group": VALID_FILTER_GROUP}),
            format="json",
        )
        assert denied.status_code == status.HTTP_403_FORBIDDEN, denied.json()

        self.organization.available_product_features = [
            {"key": AvailableFeature.LOGS_RETENTION_30D, "name": AvailableFeature.LOGS_RETENTION_30D}
        ]
        self.organization.save()

        allowed = self.client.post(
            self.spans_url,
            self._payload(config={"retention_days": 30, "filter_group": VALID_FILTER_GROUP}),
            format="json",
        )
        assert allowed.status_code == status.HTTP_201_CREATED, allowed.json()

    def test_feature_flag_gates_the_route(self):
        self._ff_patcher.stop()
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = self.client.get(self.spans_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        self._ff_patcher.start()
