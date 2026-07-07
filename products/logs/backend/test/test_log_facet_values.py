import os
import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.hogql.errors import QueryError

from posthog.clickhouse.client import sync_execute
from posthog.errors import CHQueryErrorTooManyBytes, InternalCHQueryError

from products.logs.backend.log_facet_values_query_runner import LogFacetValuesQueryRunner


class TestLogFacetValues(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    DATE_RANGE = {"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T11:00:00Z"}

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            sql = ""
            for line in f:
                log_item = json.loads(line)
                log_item["team_id"] = cls.team.id
                sql += json.dumps(log_item) + "\n"
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {sql}
            """)

    def _facet(self, facet_field: str, **filters) -> dict[str, int]:
        body = {"query": {"facetField": facet_field, "dateRange": self.DATE_RANGE, **filters}}
        response = self.client.post(f"/api/projects/{self.team.pk}/logs/facet_values", body, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {r["value"]: r["count"] for r in response.json()["results"]}

    def _facet_attr(self, key: str, **filters) -> dict[str, int]:
        body = {"query": {"facetResourceAttribute": key, "dateRange": self.DATE_RANGE, **filters}}
        response = self.client.post(f"/api/projects/{self.team.pk}/logs/facet_values", body, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {r["value"]: r["count"] for r in response.json()["results"]}

    @parameterized.expand(
        [
            ("severity_text", "severityLevels"),
            ("service_name", "serviceNames"),
        ]
    )
    def test_facet_ignores_its_own_filter(self, facet_field, own_filter_key):
        """Selecting a value in a facet must NOT change that facet's own counts (cross-filtering)."""
        base = self._facet(facet_field)
        self.assertGreater(len(base), 0)

        own_value = next(iter(base))
        filtered = self._facet(facet_field, **{own_filter_key: [own_value]})
        self.assertEqual(filtered, base, f"{facet_field} facet must ignore its own {own_filter_key} filter")

    @parameterized.expand(
        [
            ("severity_text", "service_name", "serviceNames"),
            ("service_name", "severity_text", "severityLevels"),
        ]
    )
    def test_facet_honors_other_filter(self, facet_field, other_facet_field, other_filter_key):
        """Selecting a value in another facet DOES re-scope this facet's counts (strictly fewer)."""
        base = self._facet(facet_field)
        other_value = next(iter(self._facet(other_facet_field)))

        scoped = self._facet(facet_field, **{other_filter_key: [other_value]})
        self.assertLess(
            sum(scoped.values()),
            sum(base.values()),
            f"{other_filter_key} should re-scope {facet_field} counts",
        )

    @parameterized.expand(
        [
            ("service_name", "aws"),
            ("service_name", "AWS"),
        ]
    )
    def test_facet_search_narrows_values_case_insensitively(self, facet_field, term):
        """facetSearch keeps only values containing the term (case-insensitive), independent of count."""
        base = self._facet(facet_field)
        searched = self._facet(facet_field, facetSearch=term)

        self.assertGreater(len(searched), 0)
        self.assertTrue(set(searched).issubset(set(base)))
        self.assertTrue(all(term.lower() in value.lower() for value in searched))

    def test_facet_search_with_no_matches_returns_empty(self):
        self.assertEqual(self._facet("service_name", facetSearch="no-such-service-xyz"), {})

    @parameterized.expand([("%",), ("_",)])
    def test_facet_search_treats_ilike_wildcards_literally(self, wildcard):
        """ILIKE metacharacters are escaped, so a wildcard-only search matches literally (no match-all)."""
        # No fixture service contains a literal % or _, so an escaped search returns nothing —
        # whereas an unescaped wildcard would match every service.
        self.assertEqual(self._facet("service_name", facetSearch=wildcard), {})

    def test_invalid_facet_field_is_rejected(self):
        body = {"query": {"facetField": "body", "dateRange": self.DATE_RANGE}}
        response = self.client.post(f"/api/projects/{self.team.pk}/logs/facet_values", body, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand([("k8s.namespace.name",), ("k8s.pod.name",), ("k8s.node.name",)])
    def test_facet_on_resource_attribute_returns_values(self, key):
        """A resource attribute key can be faceted and returns its values with counts."""
        result = self._facet_attr(key)
        self.assertGreater(len(result), 0)
        self.assertTrue(all(count > 0 for count in result.values()))

    def test_resource_facet_excludes_blank_for_missing_key(self):
        """Logs lacking the key read back '' from the map; that bucket must not appear as a facet value."""
        # k8s.deployment.name is present on only some fixture rows (others carry a daemonset instead).
        result = self._facet_attr("k8s.deployment.name")
        self.assertGreater(len(result), 0)
        self.assertNotIn("", result)

    def test_resource_facet_ignores_its_own_filter(self):
        """Selecting a value via a log_resource_attribute filter must not change that facet's own counts."""
        base = self._facet_attr("k8s.namespace.name")
        own_value = next(iter(base))
        filter_group = [
            {"key": "k8s.namespace.name", "type": "log_resource_attribute", "operator": "exact", "value": own_value}
        ]
        self.assertEqual(self._facet_attr("k8s.namespace.name", filterGroup=filter_group), base)

    def test_resource_facet_ignores_severity_filter(self):
        # Resource-attribute facets are served from the log_attributes rollup, which has no severity
        # dimension — a severity filter is accepted but does not re-scope the counts.
        base = self._facet_attr("k8s.namespace.name")
        self.assertGreater(len(base), 0)
        scoped = self._facet_attr("k8s.namespace.name", severityLevels=["error"])
        self.assertEqual(scoped, base)

    def test_resource_facet_honors_other_resource_attribute_filter(self):
        # A different resource-attribute filter re-scopes the counts via the rollup's
        # resource_fingerprint subquery — proves cross-filtering still works on log_attributes.
        base = self._facet_attr("k8s.pod.name")
        one_namespace = next(iter(self._facet_attr("k8s.namespace.name")))
        filter_group = [
            {"key": "k8s.namespace.name", "type": "log_resource_attribute", "operator": "exact", "value": one_namespace}
        ]
        scoped = self._facet_attr("k8s.pod.name", filterGroup=filter_group)
        self.assertGreater(len(scoped), 0)
        self.assertTrue(set(scoped).issubset(set(base)))
        self.assertLess(sum(scoped.values()), sum(base.values()))

    @parameterized.expand([("argo",), ("ARGO",)])
    def test_resource_facet_search_is_case_insensitive(self, term):
        searched = self._facet_attr("k8s.namespace.name", facetSearch=term)
        self.assertGreater(len(searched), 0)
        self.assertTrue(all(term.lower() in value.lower() for value in searched))

    def test_resource_facet_search_no_match_returns_empty(self):
        self.assertEqual(self._facet_attr("k8s.namespace.name", facetSearch="no-such-namespace-xyz"), {})

    @parameterized.expand(
        [
            # User-fixable failures (bad HogQL, or the column-facet read-byte cap tripping) must not
            # surface as opaque 500s — they become a 4xx the caller (or the MCP tool) can act on.
            ("hogql_error", QueryError("invalid facet expression"), status.HTTP_400_BAD_REQUEST),
            ("read_byte_cap", CHQueryErrorTooManyBytes("read too many bytes"), status.HTTP_400_BAD_REQUEST),
            # A genuine ClickHouse-side failure still returns a 5xx, but with a clear message rather
            # than DRF's generic "A server error occurred."
            ("internal_ch_error", InternalCHQueryError("something broke"), status.HTTP_500_INTERNAL_SERVER_ERROR),
        ]
    )
    def test_query_execution_errors_are_not_opaque_500s(self, _name, raised, expected_status):
        body = {"query": {"facetField": "service_name", "dateRange": self.DATE_RANGE}}
        with patch.object(LogFacetValuesQueryRunner, "run", side_effect=raised):
            response = self.client.post(f"/api/projects/{self.team.pk}/logs/facet_values", body, format="json")
        self.assertEqual(response.status_code, expected_status)
        # The generic DRF 500 body carries no useful detail; ours always does.
        self.assertNotEqual(response.json().get("detail"), "A server error occurred.")

    def test_requires_exactly_one_facet_target(self):
        for query in (
            {},  # neither
            {"facetField": "service_name", "facetResourceAttribute": "k8s.pod.name"},  # both
        ):
            body = {"query": {**query, "dateRange": self.DATE_RANGE}}
            response = self.client.post(f"/api/projects/{self.team.pk}/logs/facet_values", body, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
