import os
import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute


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

    def _facet_log_attr(self, key: str, **filters) -> dict[str, int]:
        body = {"query": {"facetAttribute": key, "dateRange": self.DATE_RANGE, **filters}}
        response = self.client.post(f"/api/projects/{self.team.pk}/logs/facet_values", body, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {r["value"]: r["count"] for r in response.json()["results"]}

    def _facet_multi(self, facets: list[dict], **filters) -> dict[str, dict[str, int]]:
        body = {"query": {"facets": facets, "dateRange": self.DATE_RANGE, **filters}}
        response = self.client.post(f"/api/projects/{self.team.pk}/logs/facet_values_multi", body, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        buckets: dict[str, dict[str, int]] = {}
        for r in response.json()["results"]:
            buckets.setdefault(r["facetKey"], {})[r["value"]] = r["count"]
        return buckets

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

    def test_resource_facet_honors_other_filter(self):
        """A top-level filter re-scopes a resource-attribute facet's counts (strictly fewer)."""
        base = self._facet_attr("k8s.namespace.name")
        scoped = self._facet_attr("k8s.namespace.name", severityLevels=["error"])
        self.assertLess(sum(scoped.values()), sum(base.values()))

    @parameterized.expand([("argo",), ("ARGO",)])
    def test_resource_facet_search_is_case_insensitive(self, term):
        searched = self._facet_attr("k8s.namespace.name", facetSearch=term)
        self.assertGreater(len(searched), 0)
        self.assertTrue(all(term.lower() in value.lower() for value in searched))

    def test_resource_facet_search_no_match_returns_empty(self):
        self.assertEqual(self._facet_attr("k8s.namespace.name", facetSearch="no-such-namespace-xyz"), {})

    @parameterized.expand([("method",), ("protocol",), ("level",)])
    def test_facet_on_log_attribute_returns_values(self, key):
        """A log attribute key can be faceted and returns its values with counts."""
        result = self._facet_log_attr(key)
        self.assertGreater(len(result), 0)
        self.assertTrue(all(count > 0 for count in result.values()))

    def test_log_facet_excludes_blank_for_missing_key(self):
        """Logs lacking the key read back '' from the map; that bucket must not appear as a facet value."""
        # method is present on only some fixture rows (the HTTP-style logs).
        result = self._facet_log_attr("method")
        self.assertGreater(len(result), 0)
        self.assertNotIn("", result)

    def test_log_facet_ignores_its_own_filter(self):
        """Selecting a value via a log_attribute filter must not change that facet's own counts."""
        base = self._facet_log_attr("level")
        own_value = next(iter(base))
        filter_group = [{"key": "level", "type": "log_attribute", "operator": "exact", "value": own_value}]
        self.assertEqual(self._facet_log_attr("level", filterGroup=filter_group), base)

    def test_log_facet_honors_other_filter(self):
        """A top-level filter re-scopes a log-attribute facet's counts (strictly fewer)."""
        base = self._facet_log_attr("level")
        scoped = self._facet_log_attr("level", severityLevels=["error"])
        self.assertLess(sum(scoped.values()), sum(base.values()))

    @parameterized.expand([("post",), ("POST",)])
    def test_log_facet_search_is_case_insensitive(self, term):
        searched = self._facet_log_attr("method", facetSearch=term)
        self.assertGreater(len(searched), 0)
        self.assertTrue(all(term.lower() in value.lower() for value in searched))

    def test_requires_exactly_one_facet_target(self):
        for query in (
            {},  # none
            {"facetField": "service_name", "facetResourceAttribute": "k8s.pod.name"},  # two
            {"facetField": "service_name", "facetAttribute": "method"},  # two
            {"facetResourceAttribute": "k8s.pod.name", "facetAttribute": "method"},  # two
            {  # all three
                "facetField": "service_name",
                "facetResourceAttribute": "k8s.pod.name",
                "facetAttribute": "method",
            },
        ):
            body = {"query": {**query, "dateRange": self.DATE_RANGE}}
            response = self.client.post(f"/api/projects/{self.team.pk}/logs/facet_values", body, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_multi_returns_every_facet(self):
        """A batch request returns values for column facets (from logs) and attribute facets (from log_attributes)."""
        buckets = self._facet_multi(
            [
                {"key": "level", "facetField": "severity_text"},
                {"key": "service", "facetField": "service_name"},
                {"key": "ns", "facetResourceAttribute": "k8s.namespace.name"},
                {"key": "method", "facetAttribute": "method"},
            ]
        )
        self.assertEqual(set(buckets), {"level", "service", "ns", "method"})
        # Column facets share the logs-table source with the single-facet endpoint, so they match exactly.
        self.assertEqual(buckets["level"], self._facet("severity_text"))
        self.assertEqual(buckets["service"], self._facet("service_name"))
        # Attribute facets come from the pre-aggregated log_attributes table.
        for key in ("ns", "method"):
            self.assertGreater(len(buckets[key]), 0)
            self.assertTrue(all(count > 0 for count in buckets[key].values()))
            self.assertNotIn("", buckets[key])

    def test_multi_cross_filters_each_facet_independently(self):
        """Each facet in a batch excludes only its own filter, honoring the others."""
        base = self._facet_multi(
            [
                {"key": "level", "facetField": "severity_text"},
                {"key": "service", "facetField": "service_name"},
            ]
        )
        own_level = next(iter(base["level"]))
        scoped = self._facet_multi(
            [
                {"key": "level", "facetField": "severity_text"},
                {"key": "service", "facetField": "service_name"},
            ],
            severityLevels=[own_level],
        )
        # level ignores its own severity filter; service is re-scoped by it.
        self.assertEqual(scoped["level"], base["level"])
        self.assertLessEqual(sum(scoped["service"].values()), sum(base["service"].values()))

    def test_multi_applies_per_facet_search(self):
        searched = self._facet_multi(
            [
                {"key": "service", "facetField": "service_name", "facetSearch": "aws"},
                {"key": "method", "facetAttribute": "method"},
            ]
        )
        self.assertTrue(all("aws" in value.lower() for value in searched.get("service", {})))
        self.assertGreater(len(searched.get("method", {})), 0)

    @parameterized.expand(
        [
            ("empty", []),
            ("missing_key", [{"facetField": "service_name"}]),
            ("duplicate_keys", [{"key": "a", "facetField": "service_name"}, {"key": "a", "facetAttribute": "method"}]),
            ("no_target", [{"key": "a"}]),
            ("two_targets", [{"key": "a", "facetField": "service_name", "facetAttribute": "method"}]),
        ]
    )
    def test_multi_rejects_invalid_requests(self, _name, facets):
        body = {"query": {"facets": facets, "dateRange": self.DATE_RANGE}}
        response = self.client.post(f"/api/projects/{self.team.pk}/logs/facet_values_multi", body, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
