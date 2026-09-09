import os
import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

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

    def _facet_attr(self, key: str, target: str = "facetResourceAttribute", **filters) -> dict[str, int]:
        body = {"query": {target: key, "dateRange": self.DATE_RANGE, **filters}}
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

    # Resource and log attributes share the log_attributes rollup, so every behaviour that doesn't
    # depend on resource_fingerprint is shared and parameterized over (request field, key).
    @parameterized.expand(
        [
            ("facetResourceAttribute", "k8s.namespace.name"),
            ("facetResourceAttribute", "k8s.pod.name"),
            ("facetResourceAttribute", "k8s.node.name"),
            ("facetAttribute", "log.iostream"),
            ("facetAttribute", "hostname"),
            ("facetAttribute", "level"),
        ]
    )
    def test_facet_on_attribute_returns_values(self, target, key):
        result = self._facet_attr(key, target=target)
        self.assertGreater(len(result), 0)
        self.assertTrue(all(count > 0 for count in result.values()))

    @parameterized.expand(
        [
            ("facetAttribute", "k8s.namespace.name"),
            ("facetResourceAttribute", "log.iostream"),
        ]
    )
    def test_attribute_types_are_not_interchangeable(self, target, key):
        # One rollup table holds both types, discriminated by attribute_type. A key looked up under
        # the wrong type must come back empty rather than leaking the other type's values.
        self.assertEqual(self._facet_attr(key, target=target), {})

    def test_resource_facet_excludes_blank_for_missing_key(self):
        """Logs lacking the key read back '' from the map; that bucket must not appear as a facet value."""
        # k8s.deployment.name is present on only some fixture rows (others carry a daemonset instead).
        result = self._facet_attr("k8s.deployment.name")
        self.assertGreater(len(result), 0)
        self.assertNotIn("", result)

    @parameterized.expand([("exact",), ("is_not",)])
    def test_resource_facet_ignores_its_own_filter(self, operator):
        """Selecting or excluding a value via a log_resource_attribute filter must not change that facet's own counts."""
        base = self._facet_attr("k8s.namespace.name")
        own_value = next(iter(base))
        filter_group = [
            {"key": "k8s.namespace.name", "type": "log_resource_attribute", "operator": operator, "value": own_value}
        ]
        self.assertEqual(self._facet_attr("k8s.namespace.name", filterGroup=filter_group), base)

    @parameterized.expand(
        [
            ("severity_text", "severity_level"),
            ("service_name", "service_name"),
        ]
    )
    def test_facet_ignores_its_own_log_filter_exclusion(self, facet_field, log_filter_key):
        # The rail stores column-facet exclusions as an is_not log filter in the group; the counts
        # query must strip it when faceting on that facet's own field, or an excluded value's own
        # count would zero out.
        base = self._facet(facet_field)
        own_value = next(iter(base))
        filter_group = [{"key": log_filter_key, "type": "log", "operator": "is_not", "value": [own_value]}]
        self.assertEqual(self._facet(facet_field, filterGroup=filter_group), base)

    @parameterized.expand(
        [
            ("service_name", "severity_text", "severity_level"),
            ("severity_text", "service_name", "service_name"),
        ]
    )
    def test_facet_honors_other_facets_log_filter_exclusion(self, facet_field, other_facet_field, log_filter_key):
        # An is_not log filter must remove matching rows from other facets' counts — proves the
        # NOT IN translation end to end on real data.
        base = self._facet(facet_field)
        one_value = next(iter(self._facet(other_facet_field)))
        filter_group = [{"key": log_filter_key, "type": "log", "operator": "is_not", "value": [one_value]}]
        scoped = self._facet(facet_field, filterGroup=filter_group)
        self.assertTrue(set(scoped).issubset(set(base)))
        self.assertLess(sum(scoped.values()), sum(base.values()))

    @parameterized.expand(
        [
            ("facetResourceAttribute", "k8s.namespace.name"),
            ("facetAttribute", "log.iostream"),
        ]
    )
    def test_attribute_facet_honors_severity_filter(self, target, key):
        # severity_text lives on the log_attributes rollup, so a severity filter re-scopes attribute
        # facet counts of either type (it used to be accepted but silently ignored).
        base = self._facet_attr(key, target=target)
        self.assertGreater(len(base), 0)
        one_severity = next(iter(self._facet("severity_text")))
        scoped = self._facet_attr(key, target=target, severityLevels=[one_severity])
        self.assertGreater(len(scoped), 0)
        self.assertTrue(set(scoped).issubset(set(base)))
        self.assertLess(sum(scoped.values()), sum(base.values()))

    @parameterized.expand(
        [
            ("facetResourceAttribute", "k8s.namespace.name"),
            ("facetAttribute", "log.iostream"),
        ]
    )
    def test_attribute_facet_ignores_a_column_filter_with_no_value(self, target, key):
        # The search bar writes a filter as soon as its key is picked, so a severity filter sits in
        # the group with no value while the user chooses one. Translating that to `IN ()` matches
        # nothing and empties the very list they are picking from.
        base = self._facet_attr(key, target=target)
        filter_group = [{"key": "severity_level", "type": "log", "operator": "exact", "value": []}]

        self.assertEqual(self._facet_attr(key, target=target, filterGroup=filter_group), base)

    @parameterized.expand(
        [
            ("facetResourceAttribute", "k8s.namespace.name", "severity_level", "exact"),
            ("facetResourceAttribute", "k8s.namespace.name", "severity_level", "is_not"),
            ("facetResourceAttribute", "k8s.namespace.name", "service_name", "exact"),
            ("facetResourceAttribute", "k8s.namespace.name", "service_name", "is_not"),
            ("facetAttribute", "log.iostream", "severity_level", "exact"),
            ("facetAttribute", "log.iostream", "service_name", "is_not"),
        ]
    )
    def test_attribute_facet_honors_column_filter_in_group(self, target, key, filter_key, operator):
        # The viewer keeps a level or service selection in filterGroup as a `log` filter, so these
        # counts read it from there rather than from the dedicated fields. Exclusions have only ever
        # existed in the group, which is why both polarities are covered.
        base = self._facet_attr(key, target=target)
        self.assertGreater(len(base), 0)
        facet_field = "severity_text" if filter_key == "severity_level" else "service_name"
        one_value = next(iter(self._facet(facet_field)))
        filter_group = [{"key": filter_key, "type": "log", "operator": operator, "value": [one_value]}]

        scoped = self._facet_attr(key, target=target, filterGroup=filter_group)

        self.assertGreater(len(scoped), 0)
        self.assertTrue(set(scoped).issubset(set(base)))
        self.assertLess(sum(scoped.values()), sum(base.values()))

    @parameterized.expand(
        [
            ("facetResourceAttribute", "k8s.pod.name", "exact"),
            ("facetResourceAttribute", "k8s.pod.name", "is_not"),
            ("facetAttribute", "log.iostream", "exact"),
            ("facetAttribute", "log.iostream", "is_not"),
        ]
    )
    def test_attribute_facet_honors_other_resource_attribute_filter(self, target, key, operator):
        # A resource-attribute filter — include or exclude — re-scopes the counts via the rollup's
        # resource_fingerprint subquery. Covers both facet types because a log-attribute facet reads
        # the same rollup and must keep applying resource_filter().
        base = self._facet_attr(key, target=target)
        one_namespace = next(iter(self._facet_attr("k8s.namespace.name")))
        filter_group = [
            {
                "key": "k8s.namespace.name",
                "type": "log_resource_attribute",
                "operator": operator,
                "value": one_namespace,
            }
        ]
        scoped = self._facet_attr(key, target=target, filterGroup=filter_group)
        self.assertGreater(len(scoped), 0)
        self.assertTrue(set(scoped).issubset(set(base)))
        self.assertLess(sum(scoped.values()), sum(base.values()))

    @parameterized.expand(
        [
            ("facetResourceAttribute", "k8s.namespace.name", "argo"),
            ("facetResourceAttribute", "k8s.namespace.name", "ARGO"),
            ("facetAttribute", "log.iostream", "out"),
            ("facetAttribute", "log.iostream", "OUT"),
        ]
    )
    def test_attribute_facet_search_is_case_insensitive(self, target, key, term):
        searched = self._facet_attr(key, target=target, facetSearch=term)
        self.assertGreater(len(searched), 0)
        self.assertTrue(all(term.lower() in value.lower() for value in searched))

    @parameterized.expand(
        [
            ("facetResourceAttribute", "k8s.namespace.name"),
            ("facetAttribute", "log.iostream"),
        ]
    )
    def test_attribute_facet_search_no_match_returns_empty(self, target, key):
        self.assertEqual(self._facet_attr(key, target=target, facetSearch="no-such-value-xyz"), {})

    # The batch endpoint answers several attribute facets in one query. Keys carrying a filter of
    # their own can't batch (they'd have to exclude it), so these use keys the filters never touch.
    BATCH_RESOURCE_KEYS = ["k8s.pod.name", "k8s.node.name"]
    BATCH_ATTRIBUTE_KEYS = ["log.iostream"]

    def _facet_batch(self, resource_keys, attribute_keys, **filters) -> dict[tuple[str, str], dict[str, int]]:
        body = {
            "query": {
                "facetResourceAttributes": resource_keys,
                "facetAttributes": attribute_keys,
                "dateRange": self.DATE_RANGE,
                **filters,
            }
        }
        response = self.client.post(f"/api/projects/{self.team.pk}/logs/facet_values_batch", body, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        return {
            **{
                ("resource", e["key"]): {v["value"]: v["count"] for v in e["values"]}
                for e in results["facetResourceAttributes"]
            },
            **{("log", e["key"]): {v["value"]: v["count"] for v in e["values"]} for e in results["facetAttributes"]},
        }

    def _namespace_filter(self, operator):
        return {
            "key": "k8s.namespace.name",
            "type": "log_resource_attribute",
            "operator": operator,
            "value": next(iter(self._facet_attr("k8s.namespace.name"))),
        }

    @parameterized.expand(
        [
            ("no_filters", lambda self: {}),
            ("severity", lambda self: {"severityLevels": [next(iter(self._facet("severity_text")))]}),
            ("service", lambda self: {"serviceNames": [next(iter(self._facet("service_name")))]}),
            ("resource_exact", lambda self: {"filterGroup": [self._namespace_filter("exact")]}),
            ("resource_is_not", lambda self: {"filterGroup": [self._namespace_filter("is_not")]}),
        ]
    )
    def test_batch_matches_per_facet_results(self, _name, make_filters):
        # Batching is only safe if it returns what the per-facet queries return, under every filter
        # the rollup honours. The is_not case also pins that one LogsFilterBuilder is built per
        # request: _generate_resource_attribute_filters inverts operators in place, so a second
        # builder would read the negative filter as a positive one and undercount.
        filters = make_filters(self)
        batched = self._facet_batch(self.BATCH_RESOURCE_KEYS, self.BATCH_ATTRIBUTE_KEYS, **filters)

        # Comparing the two paths alone would pass if a filter reached neither. Prove it bit first.
        if filters:
            unfiltered = self._facet_batch(self.BATCH_RESOURCE_KEYS, self.BATCH_ATTRIBUTE_KEYS)
            self.assertNotEqual(batched, unfiltered)

        for key in self.BATCH_RESOURCE_KEYS:
            single = self._facet_attr(key, **filters)
            self.assertGreater(len(single), 0)
            self.assertEqual(batched[("resource", key)], single)
        for key in self.BATCH_ATTRIBUTE_KEYS:
            single = self._facet_attr(key, target="facetAttribute", **filters)
            self.assertGreater(len(single), 0)
            self.assertEqual(batched[("log", key)], single)

    def test_batch_limits_values_per_facet(self):
        # The limit is applied per facet by a window partition. A global LIMIT would starve every
        # facet but the highest-volume one, which the equality test above can't see.
        with patch("products.logs.backend.log_facet_values_query_runner.DEFAULT_FACET_LIMIT", 2):
            batched = self._facet_batch(self.BATCH_RESOURCE_KEYS, self.BATCH_ATTRIBUTE_KEYS)

        for key in self.BATCH_RESOURCE_KEYS:
            self.assertEqual(len(batched[("resource", key)]), 2)
        for key in self.BATCH_ATTRIBUTE_KEYS:
            self.assertEqual(len(batched[("log", key)]), 2)

    def test_batch_does_not_mix_attribute_types(self):
        # One rollup holds both types, and the batch targets them as separate OR arms. A key asked
        # for under the wrong type must come back present but empty, not carrying the other's values.
        batched = self._facet_batch(["log.iostream"], ["k8s.namespace.name"])
        self.assertEqual(batched[("resource", "log.iostream")], {})
        self.assertEqual(batched[("log", "k8s.namespace.name")], {})

    @parameterized.expand(
        [
            ("no_keys", {}),
            ("empty_lists", {"facetResourceAttributes": [], "facetAttributes": []}),
            ("over_cap", {"facetAttributes": [f"key.{i}" for i in range(51)]}),
        ]
    )
    def test_batch_rejects_invalid_key_lists(self, _name, query):
        body = {"query": {**query, "dateRange": self.DATE_RANGE}}
        response = self.client.post(f"/api/projects/{self.team.pk}/logs/facet_values_batch", body, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_requires_exactly_one_facet_target(self):
        for query in (
            {},  # none
            {"facetField": "service_name", "facetResourceAttribute": "k8s.pod.name"},
            {"facetField": "service_name", "facetAttribute": "log.iostream"},
            {"facetResourceAttribute": "k8s.pod.name", "facetAttribute": "log.iostream"},
            {  # all three
                "facetField": "service_name",
                "facetResourceAttribute": "k8s.pod.name",
                "facetAttribute": "log.iostream",
            },
        ):
            body = {"query": {**query, "dateRange": self.DATE_RANGE}}
            response = self.client.post(f"/api/projects/{self.team.pk}/logs/facet_values", body, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
