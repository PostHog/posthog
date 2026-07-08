import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.traces.spans import TRACE_ATTRIBUTES_DISTRIBUTED_TABLE_SQL
from posthog.clickhouse.traces.trace_attributes import TRACE_ATTRIBUTES_TABLE_SQL

DATE_FROM = "2026-06-02T07:00:00Z"
DATE_TO = "2026-06-02T09:00:00Z"

# A value that no attribute KEY contains — so it can only match on value.
TRACE_ID_VALUE = "abc123def456trace"


class TestTracingAttributeValueSearch(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        sync_execute("DROP TABLE IF EXISTS trace_attributes_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_attributes")
        sync_execute(TRACE_ATTRIBUTES_TABLE_SQL())
        sync_execute(TRACE_ATTRIBUTES_DISTRIBUTED_TABLE_SQL())

        bucket = dt.datetime(2026, 6, 2, 8, 0, 0).strftime("%Y-%m-%d %H:%M:%S")
        # attribute_type values mirror the deployed MVs in bin/clickhouse-logs.sql.
        rows = [
            # (key, value, count, type)
            ("http.target", TRACE_ID_VALUE, 10, "span_attribute"),
            ("custom.trace_ref", TRACE_ID_VALUE, 3, "span_attribute"),
            ("http.method", "GET", 50, "span_attribute"),
            ("user.trace_id", "unrelated-value", 5, "span_attribute"),  # key contains "trace_id"
            ("k8s.pod.name", TRACE_ID_VALUE, 2, "span_resource_attribute"),
            ("service.version", "1.2.3", 20, "span_resource_attribute"),
            # ILIKE-escaping fixtures: "50%off" must not wildcard-match "50ABCoff".
            ("promo.code", "50%off", 4, "span_attribute"),
            ("promo.alt", "50ABCoff", 4, "span_attribute"),
        ]
        values_sql = ",".join(
            f"({cls.team.id}, '{bucket}', '{bucket}', 'svc', 0, '{k}', '{v}', {c}, '{t}')" for k, v, c, t in rows
        )
        sync_execute(
            "INSERT INTO trace_attributes (team_id, time_bucket, original_expiry_time_bucket, service_name, "
            "resource_fingerprint, attribute_key, attribute_value, attribute_count, attribute_type) VALUES "
            + values_sql
        )

    @classmethod
    def tearDownClass(cls):
        sync_execute("DROP TABLE IF EXISTS trace_attributes_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_attributes")
        super().tearDownClass()

    def _attributes(self, params: dict) -> list[dict]:
        query_params = {"dateRange": f'{{"date_from": "{DATE_FROM}", "date_to": "{DATE_TO}"}}', **params}
        res = self.client.get(f"/api/projects/{self.team.id}/tracing/spans/attributes", query_params)
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()["results"]

    @parameterized.expand(
        [
            # Value-only term, but value search disabled → no value matches surface.
            ("off_by_default", {"attribute_type": "span_attribute", "search": TRACE_ID_VALUE}),
            # search_values on, but term under the 4-char minimum → value search skipped.
            ("short_search", {"attribute_type": "span_attribute", "search": "abc", "search_values": "true"}),
        ]
    )
    def test_no_value_matches(self, _name, params):
        results = self._attributes(params)
        for entry in results:
            self.assertNotEqual(entry.get("matchedOn"), "value")

    def test_search_values_finds_match_on_value(self):
        results = self._attributes(
            {"attribute_type": "span_attribute", "search": TRACE_ID_VALUE, "search_values": "true"}
        )
        names = {r["name"] for r in results}
        self.assertIn("http.target", names)
        self.assertIn("custom.trace_ref", names)

        for entry in results:
            self.assertIn(entry["matchedOn"], ("key", "value"))
            if entry["matchedOn"] == "value":
                self.assertTrue(entry.get("matchedValue"))
                self.assertIn(TRACE_ID_VALUE.lower(), entry["matchedValue"].lower())

        self.assertTrue(any(r["matchedOn"] == "value" for r in results))

    def test_search_values_respects_attribute_type(self):
        # The same value lives on a resource attribute key — only returned for the resource type.
        results = self._attributes(
            {"attribute_type": "span_resource_attribute", "search": TRACE_ID_VALUE, "search_values": "true"}
        )
        names = {r["name"] for r in results}
        self.assertIn("k8s.pod.name", names)
        self.assertNotIn("http.target", names)

    def test_search_values_ranks_key_matches_first(self):
        # "trace" matches the key "user.trace_id" and the values of http.target / custom.trace_ref.
        results = self._attributes({"attribute_type": "span_attribute", "search": "trace", "search_values": "true"})
        match_kinds = [r["matchedOn"] for r in results]
        first_value_idx = next((i for i, m in enumerate(match_kinds) if m == "value"), None)
        if first_value_idx is not None:
            self.assertNotIn("key", match_kinds[first_value_idx:], "key matches must appear before value matches")

    def test_value_search_escapes_ilike_wildcards(self):
        # "%" is escaped to a literal — "50%off" must not wildcard-match "50ABCoff".
        results = self._attributes({"attribute_type": "span_attribute", "search": "50%off", "search_values": "true"})
        names = {r["name"] for r in results}
        self.assertIn("promo.code", names)
        self.assertNotIn("promo.alt", names)

    def test_key_search_is_case_insensitive(self):
        # Keys are stored lowercase; an upper-case search term must still match them (ILIKE).
        results = self._attributes({"attribute_type": "span_attribute", "search": "HTTP"})
        names = {r["name"] for r in results}
        self.assertIn("http.target", names)
        self.assertIn("http.method", names)
        self.assertTrue(all(r["matchedOn"] == "key" for r in results))

    def test_key_search_case_insensitive_with_value_search(self):
        # The value-search path matches keys case-insensitively too: "TRACE" matches the
        # key "user.trace_id" and the values of http.target / custom.trace_ref.
        results = self._attributes({"attribute_type": "span_attribute", "search": "TRACE", "search_values": "true"})
        by_name = {r["name"]: r for r in results}
        self.assertIn("user.trace_id", by_name)
        self.assertEqual(by_name["user.trace_id"]["matchedOn"], "key")
