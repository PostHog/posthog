import copy
import json

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models.team import Team
from posthog.storage.hypercache import HyperCacheDependencyUnavailable

from products.feature_flags.backend.legacy_definitions import sanitize_legacy_definitions
from products.feature_flags.backend.legacy_definitions_cache import LegacyDefinitionsHyperCache
from products.feature_flags.backend.local_evaluation import _apply_flag_dependency_transformation
from products.feature_flags.backend.sdk_cache_provider import HyperCacheFlagProvider


def definition(key, filters=None, **fields):
    return {"key": key, "filters": filters if filters is not None else {}, **fields}


def feed(flags):
    return {"flags": flags, "cohorts": {}, "group_type_mapping": {}, "minimal_flag_called_events": True}


class TestLegacyDefinitions(SimpleTestCase):
    @parameterized.expand(
        [(str(value), {"version": value, "groups": []}) for value in (2, 2.0, 3, "1", "2", True, False, None)]
        + [
            ("root_list", []),
            ("root_string", ""),
            ("root_number", 0),
            ("groups", {"groups": {}}),
            ("group", {"groups": [None]}),
            ("properties", {"groups": [{"properties": [None]}]}),
        ]
    )
    def test_excludes_invalid_targets_and_transitive_dependents(self, _name, filters):
        flags = [
            definition("healthy", {"groups": []}),
            definition("unsupported", filters, id=7, active=False, deleted=True),
        ]
        for value in (True, False):
            key = f"dependent-{value}"
            flags.append(definition(key, {"groups": [{"properties": [{"type": "flag", "key": "7", "value": value}]}]}))
            flags.append(
                definition(
                    f"transitive-{value}", {"groups": [{"properties": [{"type": "flag", "key": key, "value": value}]}]}
                )
            )
        original = feed(flags)
        before = copy.deepcopy(original)
        assert sanitize_legacy_definitions(original)["flags"] == [flags[0]]
        assert original == before

    @parameterized.expand(
        [
            ("absent", {}),
            ("integer", {"version": 1}),
            ("float", {"version": 1.0}),
            ("null_groups", {"groups": None}),
            ("null_properties", {"groups": [{"properties": None}]}),
        ]
    )
    def test_preserves_supported_values_and_order(self, _name, filters):
        payload = feed([definition("second", filters), definition("first")])
        assert sanitize_legacy_definitions(payload) is payload

    @parameterized.expand([(None,), ([],), ({},), ({"flags": {}, "cohorts": {}, "group_type_mapping": {}},)])
    def test_invalid_envelope_is_a_failure(self, payload):
        with self.assertRaises(ValueError):
            sanitize_legacy_definitions(payload)

    def test_deep_cycle_keeps_independent_definition_and_finishes_transformation(self):
        flags = [
            definition(
                str(index),
                {"groups": [{"properties": [{"type": "flag", "key": str((index + 1) % 400), "value": False}]}]},
            )
            for index in range(400)
        ]
        independent = definition("healthy")
        result = _apply_flag_dependency_transformation(feed([*flags, independent]), {})
        assert result["flags"][-1] == independent
        assert all(
            flag["filters"]["groups"][0]["properties"][0]["dependency_chain"] == [] for flag in result["flags"][:-1]
        )

    def test_malformed_nested_cohort_omits_only_affected_flags(self):
        payload = feed(
            [
                definition("healthy"),
                definition("uses-cohort", {"groups": [{"properties": [{"type": "cohort", "value": "1"}]}]}),
                definition(
                    "depends", {"groups": [{"properties": [{"type": "flag", "key": "uses-cohort", "value": False}]}]}
                ),
            ]
        )
        payload["cohorts"] = {"1": {"type": "AND", "values": [{"type": "cohort", "value": 2}]}, "2": {"values": [None]}}
        result = sanitize_legacy_definitions(payload)
        assert [flag["key"] for flag in result["flags"]] == ["healthy"]
        assert result["cohorts"] == {}


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "legacy-definitions"}}
)
class TestLegacyDefinitionsCache(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.payload = feed([definition("healthy")])
        self.loads = 0
        self.unavailable = False
        self.hypercache = LegacyDefinitionsHyperCache(
            namespace="feature_flags",
            value="flags_with_cohorts.json",
            load_fn=self.load,
            enable_etag=True,
            s3_enabled=False,
            expiry_sorted_set_key="legacy-expiry",
        )

    def load(self, key):
        self.loads += 1
        if self.unavailable:
            raise HyperCacheDependencyUnavailable()
        return self.payload

    def test_batch_verification_preserves_missing_etag_and_isolates_corrupt_entries(self):
        self.hypercache.set_cache_value(1, self.payload)
        cache.delete(self.hypercache.get_etag_key(1))
        cache.set(self.hypercache.get_cache_key(2), ["corrupt"])
        cache.set(self.hypercache._provenance_key(2), '{"etag": "invalid"}')
        assert self.hypercache.batch_get_from_cache([Team(id=1), Team(id=2)]) == {
            1: (self.payload, "redis", None),
            2: (None, "miss", None),
        }

    def test_old_cache_cannot_304_and_rebuild_retains_safe_etag(self):
        raw = json.dumps(self.payload, sort_keys=True)
        etag = self.hypercache._compute_etag(raw)
        cache.set(self.hypercache.get_cache_key(1), raw)
        cache.set(self.hypercache.get_etag_key(1), etag)
        assert self.hypercache.get_etag(1) is None
        data, current, modified = self.hypercache.get_if_none_match(1, etag)
        assert data == self.payload
        assert current == etag
        assert modified
        assert self.loads == 1
        assert self.hypercache.get_if_none_match(1, etag) == (None, etag, False)
        assert self.loads == 1

    def test_old_writer_invalidates_provenance_and_sdk_rebuilds(self):
        self.hypercache.set_cache_value(1, self.payload)
        unsafe = feed([definition("unsupported", {"version": 2}), definition("healthy")])
        raw = json.dumps(unsafe, sort_keys=True)
        cache.set(self.hypercache.get_cache_key(1), raw)
        cache.set(self.hypercache.get_etag_key(1), self.hypercache._compute_etag(raw))
        provider = HyperCacheFlagProvider.for_static_team(1)
        provider._hypercache = self.hypercache
        result = provider.get_flag_definitions()
        assert result is not None
        assert result["flags"] == self.payload["flags"]
        assert self.loads == 1

    def test_supplied_payload_filters_before_publishing_to_both_tiers(self):
        objects = {}
        self.hypercache.s3_enabled = True
        with (
            patch("posthog.storage.object_storage.write", side_effect=lambda key, value: objects.update({key: value})),
            patch("posthog.storage.object_storage.read", side_effect=lambda key, **kwargs: objects.get(key)),
        ):
            mixed = feed([definition("unsupported", {"version": 2}), definition("healthy")])
            assert self.hypercache.update_cache(1, data=mixed)
            etag = self.hypercache.get_etag(1)
            assert self.hypercache.get_from_cache(1) == self.payload
            cache.clear()
            assert self.hypercache.get_from_cache_with_source(1) == (self.payload, "s3")
            assert self.hypercache.get_etag(1) == etag
            assert self.loads == 0

    def test_invalid_envelope_and_dependency_failure_preserve_previous_entry(self):
        self.hypercache.set_cache_value(1, self.payload)
        etag = self.hypercache.get_etag(1)
        assert not self.hypercache.update_cache(1, data={"flags": []})
        self.unavailable = True
        assert not self.hypercache.update_cache(1)
        assert self.hypercache.get_from_cache(1) == self.payload
        assert self.hypercache.get_etag(1) == etag

    def test_cold_unverified_mirror_keeps_retrying_without_caching_a_miss(self):
        self.unavailable = True
        for _ in range(2):
            assert self.hypercache.get_from_cache_with_source("mirror") == (None, "dependency_unavailable")
        assert cache.get(self.hypercache.get_cache_key("mirror")) is None
        assert self.loads == 2
