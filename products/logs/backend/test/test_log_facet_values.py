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
