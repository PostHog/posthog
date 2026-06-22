import os
import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute


class TestLogFieldValues(ClickhouseTestMixin, APIBaseTest):
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

    def _field(self, column: str, **filters) -> dict[str, int]:
        body = {"query": {"column": column, "dateRange": self.DATE_RANGE, **filters}}
        response = self.client.post(f"/api/projects/{self.team.pk}/logs/field_values", body, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {r["value"]: r["count"] for r in response.json()["results"]}

    def _field_attr(self, key: str, **filters) -> dict[str, int]:
        body = {"query": {"resourceAttribute": key, "dateRange": self.DATE_RANGE, **filters}}
        response = self.client.post(f"/api/projects/{self.team.pk}/logs/field_values", body, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {r["value"]: r["count"] for r in response.json()["results"]}

    @parameterized.expand(
        [
            ("severity_text", "severityLevels"),
            ("service_name", "serviceNames"),
        ]
    )
    def test_field_ignores_its_own_filter(self, column, own_filter_key):
        """Selecting a value in a field must NOT change that field's own counts (cross-filtering)."""
        base = self._field(column)
        self.assertGreater(len(base), 0)

        own_value = next(iter(base))
        filtered = self._field(column, **{own_filter_key: [own_value]})
        self.assertEqual(filtered, base, f"{column} field must ignore its own {own_filter_key} filter")

    @parameterized.expand(
        [
            ("severity_text", "service_name", "serviceNames"),
            ("service_name", "severity_text", "severityLevels"),
        ]
    )
    def test_field_honors_other_filter(self, column, other_column, other_filter_key):
        """Selecting a value in another field DOES re-scope this field's counts (strictly fewer)."""
        base = self._field(column)
        other_value = next(iter(self._field(other_column)))

        scoped = self._field(column, **{other_filter_key: [other_value]})
        self.assertLess(
            sum(scoped.values()),
            sum(base.values()),
            f"{other_filter_key} should re-scope {column} counts",
        )

    @parameterized.expand(
        [
            ("service_name", "aws"),
            ("service_name", "AWS"),
        ]
    )
    def test_field_search_narrows_values_case_insensitively(self, column, term):
        """fieldSearch keeps only values containing the term (case-insensitive), independent of count."""
        base = self._field(column)
        searched = self._field(column, fieldSearch=term)

        self.assertGreater(len(searched), 0)
        self.assertTrue(set(searched).issubset(set(base)))
        self.assertTrue(all(term.lower() in value.lower() for value in searched))

    def test_field_search_with_no_matches_returns_empty(self):
        self.assertEqual(self._field("service_name", fieldSearch="no-such-service-xyz"), {})

    @parameterized.expand([("%",), ("_",)])
    def test_field_search_treats_ilike_wildcards_literally(self, wildcard):
        """ILIKE metacharacters are escaped, so a wildcard-only search matches literally (no match-all)."""
        # No fixture service contains a literal % or _, so an escaped search returns nothing —
        # whereas an unescaped wildcard would match every service.
        self.assertEqual(self._field("service_name", fieldSearch=wildcard), {})

    def test_invalid_column_is_rejected(self):
        body = {"query": {"column": "body", "dateRange": self.DATE_RANGE}}
        response = self.client.post(f"/api/projects/{self.team.pk}/logs/field_values", body, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand([("k8s.namespace.name",), ("k8s.pod.name",), ("k8s.node.name",)])
    def test_field_on_resource_attribute_returns_values(self, key):
        """A resource attribute key can be used as a field and returns its values with counts."""
        result = self._field_attr(key)
        self.assertGreater(len(result), 0)
        self.assertTrue(all(count > 0 for count in result.values()))

    def test_resource_field_excludes_blank_for_missing_key(self):
        """Logs lacking the key read back '' from the map; that bucket must not appear as a field value."""
        # k8s.deployment.name is present on only some fixture rows (others carry a daemonset instead).
        result = self._field_attr("k8s.deployment.name")
        self.assertGreater(len(result), 0)
        self.assertNotIn("", result)

    def test_resource_field_ignores_its_own_filter(self):
        """Selecting a value via a log_resource_attribute filter must not change that field's own counts."""
        base = self._field_attr("k8s.namespace.name")
        own_value = next(iter(base))
        filter_group = [
            {"key": "k8s.namespace.name", "type": "log_resource_attribute", "operator": "exact", "value": own_value}
        ]
        self.assertEqual(self._field_attr("k8s.namespace.name", filterGroup=filter_group), base)

    def test_resource_field_honors_other_filter(self):
        """A top-level filter re-scopes a resource-attribute field's counts (strictly fewer)."""
        base = self._field_attr("k8s.namespace.name")
        scoped = self._field_attr("k8s.namespace.name", severityLevels=["error"])
        self.assertLess(sum(scoped.values()), sum(base.values()))

    @parameterized.expand([("argo",), ("ARGO",)])
    def test_resource_field_search_is_case_insensitive(self, term):
        searched = self._field_attr("k8s.namespace.name", fieldSearch=term)
        self.assertGreater(len(searched), 0)
        self.assertTrue(all(term.lower() in value.lower() for value in searched))

    def test_resource_field_search_no_match_returns_empty(self):
        self.assertEqual(self._field_attr("k8s.namespace.name", fieldSearch="no-such-namespace-xyz"), {})

    def test_requires_exactly_one_field_target(self):
        for query in (
            {},  # neither
            {"column": "service_name", "resourceAttribute": "k8s.pod.name"},  # both
        ):
            body = {"query": {**query, "dateRange": self.DATE_RANGE}}
            response = self.client.post(f"/api/projects/{self.team.pk}/logs/field_values", body, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
