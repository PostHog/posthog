import copy
import json
from typing import Any

from unittest.mock import Mock, patch

from django.core.cache import cache, caches
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models.team import Team
from posthog.storage.hypercache import HYPERCACHE_MIRROR_FAILURE_COUNTER, HyperCacheDependencyUnavailable, KeyType

from products.feature_flags.backend.cache_keys import EU_CROSS_REGION_MIRROR_CACHE_KEY
from products.feature_flags.backend.cross_region_flag_sync import sync_cross_region_flags
from products.feature_flags.backend.legacy_definitions import sanitize_legacy_definitions
from products.feature_flags.backend.legacy_definitions_cache import LegacyDefinitionsHyperCache
from products.feature_flags.backend.local_evaluation import _apply_flag_dependency_transformation
from products.feature_flags.backend.sdk_cache_provider import HyperCacheFlagProvider


def definition(key: str, filters: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    return {"key": key, "filters": filters if filters is not None else {}, **fields}


def feed(flags: list[dict[str, Any]]) -> dict[str, Any]:
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
    def test_excludes_invalid_targets_and_transitive_dependents(self, _name: str, filters: Any) -> None:
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
    def test_preserves_supported_values_and_order(self, _name: str, filters: Any) -> None:
        payload = feed([definition("second", filters), definition("first")])
        assert sanitize_legacy_definitions(payload) is payload

    @parameterized.expand([(None,), ([],), ({},), ({"flags": {}, "cohorts": {}, "group_type_mapping": {}},)])
    def test_invalid_envelope_is_a_failure(self, payload: Any) -> None:
        with self.assertRaises(ValueError):
            sanitize_legacy_definitions(payload)

    def test_deep_cycle_keeps_independent_definition_and_finishes_transformation(self) -> None:
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

    def test_malformed_nested_cohort_omits_only_affected_flags(self) -> None:
        payload = feed(
            [
                definition("healthy", {"groups": [{"properties": [{"type": "cohort", "value": "3"}]}]}),
                definition("uses-cohort", {"groups": [{"properties": [{"type": "cohort", "value": "1"}]}]}),
                definition(
                    "depends", {"groups": [{"properties": [{"type": "flag", "key": "uses-cohort", "value": False}]}]}
                ),
            ]
        )
        payload["cohorts"] = {
            "1": {"type": "AND", "values": [{"type": "cohort", "value": 2}]},
            "2": {"values": [None]},
            "3": {"type": "AND", "values": [{"type": "cohort", "value": 4}]},
            "4": {"type": "AND", "values": [{"type": "person", "key": "tier", "value": "example"}]},
        }
        result = sanitize_legacy_definitions(payload)
        assert [flag["key"] for flag in result["flags"]] == ["healthy"]
        assert result["cohorts"] == {key: payload["cohorts"][key] for key in ("3", "4")}


@override_settings(
    FLAG_DEFINITIONS_REQUIRE_PROVENANCE=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "legacy-definitions"}},
)
class TestLegacyDefinitionsCache(SimpleTestCase):
    def setUp(self) -> None:
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

    def load(self, key: KeyType) -> dict[str, Any]:
        self.loads += 1
        if self.unavailable:
            raise HyperCacheDependencyUnavailable()
        return self.payload

    def test_batch_verification_preserves_missing_etag_and_isolates_corrupt_entries(self) -> None:
        self.hypercache.set_cache_value(1, self.payload)
        cache.delete(self.hypercache.get_etag_key(1))
        cache.set(self.hypercache.get_cache_key(2), ["corrupt"])
        cache.set(self.hypercache._provenance_key(2), '{"etag": "invalid"}')
        assert self.hypercache.batch_get_from_cache([Team(id=1), Team(id=2)]) == {
            1: (self.payload, "redis", None),
            2: (None, "miss", None),
        }

    def test_old_cache_cannot_304_and_rebuild_retains_safe_etag(self) -> None:
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

    @override_settings(FLAG_DEFINITIONS_REQUIRE_PROVENANCE=False)
    def test_legacy_cache_stays_readable_while_verifier_and_unchanged_writes_add_provenance(self) -> None:
        raw = json.dumps(self.payload, sort_keys=True)
        etag = self.hypercache._compute_etag(raw)
        cache.set(self.hypercache.get_cache_key(1), raw)
        cache.set(self.hypercache.get_etag_key(1), etag)
        assert self.hypercache.get_from_cache(1) == self.payload
        assert self.hypercache.get_if_none_match(1, etag) == (None, etag, False)
        assert self.loads == 0
        assert self.hypercache.batch_get_from_cache([Team(id=1)])[1][1] == "miss"
        self.hypercache.set_cache_value(1, self.payload, skip_if_unchanged=True)
        with override_settings(FLAG_DEFINITIONS_REQUIRE_PROVENANCE=True):
            assert self.hypercache.get_if_none_match(1, etag) == (None, etag, False)
            assert self.hypercache.get_from_cache(1) == self.payload
        assert self.loads == 0

    @override_settings(
        FLAG_DEFINITIONS_REQUIRE_PROVENANCE=False,
        CLOUD_DEPLOYMENT="EU",
        POSTHOG_FLAGS_PROJECT_SECRET_TOKEN="phs_test_token",
    )
    def test_mirror_rollout_requires_verified_full_response_before_trusting_legacy_data(self) -> None:
        objects: dict[str, str] = {}
        self.hypercache.s3_enabled = True
        self.unavailable = True
        key = EU_CROSS_REGION_MIRROR_CACHE_KEY
        response = Mock(status_code=200, headers={})
        response.json.return_value = self.payload
        with (
            patch("posthog.storage.object_storage.write", side_effect=lambda key, value: objects.update({key: value})),
            patch("posthog.storage.object_storage.read", side_effect=lambda key, **kwargs: objects.get(key)),
            patch("posthog.storage.object_storage.delete", side_effect=lambda key: objects.pop(key, None)),
            patch("products.feature_flags.backend.cross_region_flag_sync.flag_definitions_hypercache", self.hypercache),
            patch(
                "products.feature_flags.backend.cross_region_flag_sync.requests.get", return_value=response
            ) as request,
        ):
            self.hypercache.set_cache_value(key, self.payload)
            sync_cross_region_flags()
            assert self.hypercache.get_from_cache(key) == self.payload
            assert self.hypercache.get_verified_etag(key) is None
            cache.clear()
            assert self.hypercache.get_from_cache_with_source(key) == (self.payload, "s3")
            assert self.hypercache.get_verified_etag(key) is None
            with override_settings(FLAG_DEFINITIONS_REQUIRE_PROVENANCE=True):
                assert self.hypercache.get_from_cache_with_source(key) == (None, "dependency_unavailable")
                sync_cross_region_flags()
                assert self.hypercache.get_from_cache(key) is None
            response.headers = {"x-posthog-legacy-definitions": "1"}
            sync_cross_region_flags()
            assert "If-None-Match" not in request.call_args.kwargs["headers"]
            with override_settings(FLAG_DEFINITIONS_REQUIRE_PROVENANCE=True):
                assert self.hypercache.get_from_cache(key) == self.payload
                etag = self.hypercache.get_etag(key)
                assert etag
                response.status_code = 304
                sync_cross_region_flags()
                assert request.call_args.kwargs["headers"]["If-None-Match"] == f'"{etag}"'
                assert self.hypercache.get_from_cache(key) == self.payload

    def test_old_writer_invalidates_provenance_and_sdk_rebuilds(self) -> None:
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

    @parameterized.expand([("flags", {}), ("cohorts", []), ("group_type_mapping", [])])
    def test_matching_provenance_does_not_allow_an_invalid_envelope(self, field: str, value: Any) -> None:
        raw = json.dumps({**self.payload, field: value}, sort_keys=True)
        cache.set(self.hypercache.get_cache_key(1), raw)
        cache.set(self.hypercache._provenance_key(1), json.dumps({"etag": self.hypercache._compute_etag(raw)}))
        assert self.hypercache.get_from_cache_with_source(1) == (self.payload, "db")
        assert self.loads == 1

    @parameterized.expand([("primary",), ("secondary",)])
    @override_settings(
        CACHES={
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "legacy-primary"},
            "secondary": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "legacy-secondary"},
        }
    )
    def test_corrupt_provenance_reports_etag_read_failures(self, tier: str) -> None:
        self.hypercache.secondary_cache_client = caches["secondary"]
        self.hypercache.set_cache_value(1, self.payload)
        client = cache if tier == "primary" else caches["secondary"]
        client.set(self.hypercache._provenance_key(1), "{invalid json")
        counter = HYPERCACHE_MIRROR_FAILURE_COUNTER.labels(
            namespace=self.hypercache.namespace, value=self.hypercache.value
        )
        failures_before = counter._value.get()
        with patch("products.feature_flags.backend.legacy_definitions_cache.capture_exception") as capture:
            if tier == "primary":
                assert self.hypercache.get_etag(1) is None
            else:
                self.hypercache.set_cache_value(1, self.payload, skip_if_unchanged=True)
                assert caches["secondary"].get(self.hypercache._provenance_key(1)) == cache.get(
                    self.hypercache._provenance_key(1)
                )
        capture.assert_called_once()
        assert isinstance(capture.call_args.args[0], ValueError)
        assert counter._value.get() == failures_before + (tier == "secondary")

    def test_supplied_payload_filters_before_publishing_to_both_tiers(self) -> None:
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

    def test_invalid_envelope_and_dependency_failure_preserve_previous_entry(self) -> None:
        self.hypercache.set_cache_value(1, self.payload)
        etag = self.hypercache.get_etag(1)
        assert not self.hypercache.update_cache(1, data={"flags": []})
        self.unavailable = True
        assert not self.hypercache.update_cache(1)
        assert self.hypercache.get_from_cache(1) == self.payload
        assert self.hypercache.get_etag(1) == etag

    def test_cold_unverified_mirror_keeps_retrying_without_caching_a_miss(self) -> None:
        self.unavailable = True
        for _ in range(2):
            assert self.hypercache.get_from_cache_with_source("mirror") == (None, "dependency_unavailable")
        assert cache.get(self.hypercache.get_cache_key("mirror")) is None
        assert self.loads == 2
