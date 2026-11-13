import json
import time
import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache as django_cache
from django.test import override_settings

from jsonschema import Draft202012Validator
from parameterized import parameterized
from prometheus_client import REGISTRY
from referencing import Registry, Resource
from structlog.testing import capture_logs

from posthog.dataclasses import frozen
from posthog.models.group_type_mapping import GroupTypesUnavailable
from posthog.models.project import Project
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage import cache_expiry_manager, object_storage
from posthog.storage.hypercache import HyperCache
from posthog.storage.hypercache_verifier import VerificationResult, verify_and_fix_all_teams
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.feature_flags.backend.facade.config import detect_config_format, v2_config_lookup
from products.feature_flags.backend.local_evaluation import (
    _get_flags_response_for_local_evaluation,
    flag_definitions_hypercache,
)
from products.feature_flags.backend.local_evaluation_v2 import (
    FLAG_DEFINITIONS_V2_CACHE_EXPIRY_SORTED_SET,
    FLAG_DEFINITIONS_V2_CACHE_TYPE,
    FLAG_DEFINITIONS_V2_HYPERCACHE_MANAGEMENT_CONFIG,
    flag_definitions_v2_hypercache,
    update_flag_definitions_v2_cache,
    verify_team_flag_definitions_v2,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.tasks import (
    clear_team_definitions_cache,
    maintain_flag_definitions_v2_cache_entries,
    update_team_flags_cache,
)
from products.surveys.backend.models import Survey

MODULE = "products.feature_flags.backend.local_evaluation_v2"
LEGACY_MODULE = "products.feature_flags.backend.local_evaluation"
# Vendored from the harness contract; SOURCE.json records the revision and digests.
CONTRACT_DIR = Path(__file__).parent / "fixtures" / "rules_v2_contract"


def _contract(relative: str) -> Any:
    return json.loads((CONTRACT_DIR / relative).read_text(encoding="utf-8"))


BOOLEAN_V2 = _contract("fixtures/config/valid/boolean_targeted_and_percentage_rollout.json")
EXPERIMENT_V2 = _contract("fixtures/config/valid/experiment_rule_local_holdout.json")
FLOAT_VERSION_V2 = _contract("fixtures/config/valid/version_float_literal.json")
INVALID_V2 = {"version": 2, "return_type": "boolean", "default_value": False, "rules": "not-a-list"}
V1_FILTERS = {
    "groups": [
        {
            "properties": [{"key": "plan", "type": "person", "value": "pro", "operator": "exact"}],
            "rollout_percentage": 50,
        }
    ]
}
LEGACY = flag_definitions_hypercache
V2 = flag_definitions_v2_hypercache


@frozen
class _StoredEntry:
    text: str | None
    etag: str | None


ABSENT = _StoredEntry(text=None, etag=None)


def _feed_validator() -> Draft202012Validator:
    feed, entry, config = (
        _contract(f"schemas/{name}.schema.json") for name in ("definitions_v2", "definitions_entry", "config")
    )
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in (entry, config))
    return Draft202012Validator(feed, registry=registry)


def _create_flag(team: Team, key: str, filters: Any, **fields: Any) -> FeatureFlag:
    flag = FeatureFlag.objects.create(team=team, key=key, filters={}, **fields)
    FeatureFlag.objects_including_soft_deleted.filter(pk=flag.pk).update(filters=filters)
    return flag


def _etag(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _stored(cache: HyperCache, team: Team) -> _StoredEntry:
    client = cache.cache_client
    return _StoredEntry(text=client.get(cache.get_cache_key(team)), etag=client.get(cache.get_etag_key(team)))


def _body(cache: HyperCache, team: Team) -> dict[str, Any]:
    entry = _stored(cache, team)
    assert entry.text is not None
    assert entry.etag == _etag(entry.text)
    return json.loads(entry.text)


def _tracked_score(team: Team) -> float | None:
    return get_client(V2.redis_url).zscore(FLAG_DEFINITIONS_V2_CACHE_EXPIRY_SORTED_SET, str(team.id))


def _keys(body: dict[str, Any]) -> list[str]:
    return [flag["key"] for flag in body["flags"]]


def _v2_counter(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, {"namespace": "feature_flags", "value": V2.value, **labels}) or 0.0


class DefinitionsV2TestCase(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._clear_entries(self.team.id)
        self.addCleanup(self._clear_entries, self.team.id)

    @staticmethod
    def _clear_entries(team_id: int) -> None:
        LEGACY.delete_cache_entry(team_id)
        V2.delete_cache_entry(team_id)

    def _other_team(self, name: str = "Other") -> Team:
        _, team = Project.objects.create_with_team(initiating_user=self.user, organization=self.organization, name=name)
        self.addCleanup(self._clear_entries, team.id)
        return team

    def _rebuild(self, team: Team | None = None) -> None:
        update_team_flags_cache((team or self.team).id)

    def _create_v1_flags(self) -> None:
        alpha = _create_flag(self.team, "alpha", V1_FILTERS)
        dependency = {"key": str(alpha.pk), "type": "flag", "value": True, "operator": "flag_evaluates_to"}
        _create_flag(self.team, "beta", {"groups": [{"properties": [dependency], "rollout_percentage": 100}]})

    def _create_v2_flags(self) -> None:
        _create_flag(self.team, "v2-boolean", BOOLEAN_V2)
        _create_flag(self.team, "v2-experiment", EXPERIMENT_V2)
        _create_flag(self.team, "v2-inactive", BOOLEAN_V2, active=False)


class TestV2ConfigLookup(BaseTest):
    @parameterized.expand(
        [
            ("absent_version", {"groups": []}),
            ("version_1", {"version": 1}),
            ("version_2", {"version": 2}),
            ("version_2_float", {"version": 2.0}),
            ("version_true", {"version": True}),
            ("version_string", {"version": "2"}),
            ("version_null", {"version": None}),
            ("unknown_future_version", {"version": 3}),
            ("fractional_version", {"version": 2.5}),
            ("list_document", [{"version": 2}]),
            ("string_document", "version"),
        ]
    )
    def test_lookup_agrees_with_format_detection(self, _name: str, filters: Any) -> None:
        flag = _create_flag(self.team, "flag", filters)

        matched = FeatureFlag.objects.filter(pk=flag.pk, **v2_config_lookup()).exists()

        assert matched == (detect_config_format(filters).kind == "v2")


class TestLegacyEntryIsUnchanged(DefinitionsV2TestCase):
    def _create_malformed_rows(self) -> None:
        _create_flag(self.team, "malformed-v1", {"groups": [{"properties": {}}]})
        _create_flag(self.team, "malformed-v2", INVALID_V2)
        _create_flag(self.team, "unknown-version", {"version": 3})

    @parameterized.expand(
        [
            ("v1_only", True, False, False),
            ("mixed", True, True, False),
            ("v2_only", False, True, False),
            ("malformed_rows", True, True, True),
        ]
    )
    def test_legacy_body_and_etag_replay(self, _name: str, with_v1: bool, with_v2: bool, with_malformed: bool) -> None:
        if with_v1:
            self._create_v1_flags()
        self._rebuild()
        baseline = _stored(LEGACY, self.team)

        if with_v2:
            self._create_v2_flags()
        if with_malformed:
            self._create_malformed_rows()
        self._rebuild()

        # The rows the legacy feed leaves out change neither its bytes nor its ETag.
        assert _stored(LEGACY, self.team) == baseline
        built = json.dumps(_get_flags_response_for_local_evaluation(self.team), sort_keys=True)
        assert baseline == _StoredEntry(text=built, etag=_etag(built))
        legacy = json.loads(built)
        assert _keys(legacy) == (["alpha", "beta"] if with_v1 else [])
        assert all(flag["filters"].get("version") != 2 for flag in legacy["flags"])
        assert (_stored(V2, self.team) != ABSENT) == with_v2

    def test_v2_failure_leaves_the_legacy_entry_and_its_etag_untouched(self) -> None:
        self._create_v1_flags()
        self._create_v2_flags()
        self._rebuild()
        v2_before = _stored(V2, self.team)
        failures_before = _v2_counter("posthog_hypercache_sync_total", result="failure")
        _create_flag(self.team, "gamma", V1_FILTERS)

        with patch.object(V2, "set_cache_value", side_effect=RuntimeError("write failed")), capture_logs() as logs:
            self._rebuild()

        built = json.dumps(_get_flags_response_for_local_evaluation(self.team), sort_keys=True)
        assert _keys(json.loads(built)) == ["alpha", "beta", "gamma"]
        assert _stored(LEGACY, self.team) == _StoredEntry(text=built, etag=_etag(built))
        assert _stored(V2, self.team) == v2_before
        assert _v2_counter("posthog_hypercache_sync_total", result="failure") == failures_before + 1
        assert "Failed to sync flag definitions v2 cache for team" in [log["event"] for log in logs]

    def test_legacy_build_failure_keeps_the_previous_v2_entry(self) -> None:
        self._create_v1_flags()
        self._create_v2_flags()
        self._rebuild()
        v2_before = _stored(V2, self.team)
        _create_flag(self.team, "v2-added", BOOLEAN_V2)

        with patch(
            f"{LEGACY_MODULE}._transform_flag_property_dependencies",
            side_effect=RuntimeError("transformation failed"),
        ):
            self._rebuild()

        assert _stored(V2, self.team) == v2_before


class TestDefinitionsV2Body(DefinitionsV2TestCase):
    def test_body_is_the_legacy_response_plus_one_entry_per_v2_flag(self) -> None:
        self._create_v1_flags()
        self._create_v2_flags()
        self._rebuild()

        legacy = _body(LEGACY, self.team)
        body = _body(V2, self.team)

        assert body["flags"][: len(legacy["flags"])] == legacy["flags"]
        assert {**body, "flags": legacy["flags"]} == legacy
        entries = {flag["key"]: flag for flag in body["flags"][len(legacy["flags"]) :]}
        assert list(entries) == ["v2-boolean", "v2-experiment", "v2-inactive"]
        for entry in entries.values():
            assert set(entry) == set(legacy["flags"][0])
        # The stored document as it is, with its rule and holdout seeds.
        assert entries["v2-boolean"]["filters"] == BOOLEAN_V2
        assert entries["v2-experiment"]["filters"] == EXPERIMENT_V2
        assert entries["v2-experiment"]["filters"]["rules"][0]["seed"] == "checkout-layout-split"
        assert entries["v2-experiment"]["filters"]["rules"][0]["holdout"]["seed"] == "checkout-layout-holdout"
        assert [entry["active"] for entry in entries.values()] == [True, True, False]
        assert _stored(V2, self.team).etag != _stored(LEGACY, self.team).etag

    def test_body_validates_against_the_contract_schemas(self) -> None:
        self._create_v1_flags()
        self._create_v2_flags()
        _create_flag(self.team, "v2-float-version", FLOAT_VERSION_V2)
        self._rebuild()
        body = _body(V2, self.team)
        validator = _feed_validator()

        assert [error.message for error in validator.iter_errors(body)] == []

        # The schema is closed for a v2 entry: one without its seed does not validate.
        broken = deepcopy(body)
        experiment = next(flag for flag in broken["flags"] if flag["key"] == "v2-experiment")
        del experiment["filters"]["rules"][0]["seed"]
        assert list(validator.iter_errors(broken))

    def test_rows_the_feed_cannot_carry_are_left_out(self) -> None:
        _create_flag(self.team, "v2-float-version", FLOAT_VERSION_V2)
        _create_flag(self.team, "v2-deleted", BOOLEAN_V2, deleted=True)
        _create_flag(self.team, "v2-encrypted", BOOLEAN_V2, is_remote_configuration=True, has_encrypted_payloads=True)
        survey_flag = FeatureFlag.objects.create(team=self.team, key="v2-survey", filters={})
        Survey.objects.create(team=self.team, name="Survey", type="popover", targeting_flag=survey_flag)
        FeatureFlag.objects.filter(pk=survey_flag.pk).update(filters=BOOLEAN_V2)
        invalid = _create_flag(self.team, "v2-invalid", INVALID_V2)

        with capture_logs() as logs:
            self._rebuild()

        assert _keys(_body(V2, self.team)) == ["v2-float-version"]
        omitted = [log for log in logs if log["event"] == "Invalid v2 feature flag omitted from definitions"]
        assert [(log["team_id"], log["flag_id"]) for log in omitted] == [(self.team.id, invalid.pk)]

    def test_entry_of_a_team_with_only_invalid_v2_rows_equals_its_legacy_entry(self) -> None:
        self._create_v1_flags()
        _create_flag(self.team, "v2-invalid", INVALID_V2)
        self._rebuild()

        assert _stored(V2, self.team) == _stored(LEGACY, self.team) != ABSENT


class TestDefinitionsV2EntryLifecycle(DefinitionsV2TestCase):
    def test_entry_sits_beside_the_legacy_entry_on_the_same_redis_tiers(self) -> None:
        assert V2.get_cache_key(self.team) == f"cache/teams/{self.team.id}/feature_flags/flags_with_cohorts_v2.json"
        assert V2.cache_client is LEGACY.cache_client
        assert V2.secondary_cache_client is LEGACY.secondary_cache_client

    def test_team_without_v2_flags_costs_one_query_and_no_redis_call(self) -> None:
        self._create_v1_flags()

        with (
            self.assertNumQueries(1),
            patch.object(V2, "cache_client") as primary,
            patch.object(V2, "secondary_cache_client") as mirror,
            patch(f"{MODULE}.get_client") as raw_client,
        ):
            assert update_flag_definitions_v2_cache(self.team, skip_if_unchanged=True, entry_expected=False) is True

        assert primary.mock_calls == mirror.mock_calls == raw_client.mock_calls == []
        self._rebuild()
        assert _stored(V2, self.team) == ABSENT
        assert _tracked_score(self.team) is None

    def test_entry_lives_in_redis_only_and_a_miss_is_not_loaded(self) -> None:
        self._create_v2_flags()
        self._rebuild()
        assert object_storage.read(V2.get_cache_key(self.team), missing_ok=True) is None

        V2.delete_cache_entry(self.team)
        assert V2.get_from_cache(self.team) is None
        assert _stored(V2, self.team) == ABSENT

    def test_unchanged_rebuild_skips_the_write(self) -> None:
        self._create_v2_flags()
        self._rebuild()
        skipped_before = _v2_counter("posthog_hypercache_write_skipped_unchanged_total")

        self._rebuild()

        assert _v2_counter("posthog_hypercache_write_skipped_unchanged_total") == skipped_before + 1

    def test_entry_goes_when_the_last_v2_flag_is_deleted(self) -> None:
        self._create_v1_flags()
        first = _create_flag(self.team, "v2-first", BOOLEAN_V2)
        second = _create_flag(self.team, "v2-second", EXPERIMENT_V2)
        self._rebuild()
        assert _tracked_score(self.team) is not None

        FeatureFlag.objects.filter(pk=first.pk).update(deleted=True)
        self._rebuild()
        assert _keys(_body(V2, self.team)) == ["alpha", "beta", "v2-second"]

        FeatureFlag.objects.filter(pk=second.pk).update(deleted=True)
        self._rebuild()
        assert _stored(V2, self.team) == ABSENT
        assert _tracked_score(self.team) is None
        assert _keys(_body(LEGACY, self.team)) == ["alpha", "beta"]

        # With the entry gone, a later rebuild of this team deletes nothing.
        with patch.object(V2.cache_client, "delete") as delete, patch(f"{MODULE}.get_client") as raw_client:
            assert update_flag_definitions_v2_cache(self.team, skip_if_unchanged=True, entry_expected=False) is True
        delete.assert_not_called()
        raw_client.assert_not_called()

    def test_failed_removal_keeps_the_entry_tracked_for_upkeep(self) -> None:
        flag = _create_flag(self.team, "v2-boolean", BOOLEAN_V2)
        self._rebuild()
        FeatureFlag.objects.filter(pk=flag.pk).update(deleted=True)

        with patch.object(V2.cache_client, "delete", side_effect=ConnectionError("redis down")):
            assert update_flag_definitions_v2_cache(self.team, skip_if_unchanged=True, entry_expected=False) is False
        assert _stored(V2, self.team) != ABSENT
        assert _tracked_score(self.team) is not None

        maintain_flag_definitions_v2_cache_entries()

        assert _stored(V2, self.team) == ABSENT
        assert _tracked_score(self.team) is None

    def test_entry_of_a_hard_deleted_last_v2_flag_is_removed_by_upkeep(self) -> None:
        flag = _create_flag(self.team, "v2-boolean", BOOLEAN_V2)
        self._rebuild()
        FeatureFlag.objects_including_soft_deleted.filter(pk=flag.pk).delete()

        # No row is left to tell the rebuild after a flag change that an entry existed.
        self._rebuild()
        assert _stored(V2, self.team) != ABSENT
        assert verify_team_flag_definitions_v2(self.team)["issue"] == "STALE_ENTRY"

        maintain_flag_definitions_v2_cache_entries()

        assert _stored(V2, self.team) == ABSENT
        assert _tracked_score(self.team) is None

    def test_clearing_a_team_removes_both_entries(self) -> None:
        self._create_v1_flags()
        self._create_v2_flags()
        self._rebuild()

        clear_team_definitions_cache(self.team.id)

        assert _stored(LEGACY, self.team) == ABSENT
        assert _stored(V2, self.team) == ABSENT
        assert _tracked_score(self.team) is None

    def test_group_mapping_guards_apply_to_the_v2_entry(self) -> None:
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        self._create_v2_flags()
        self._rebuild()
        before = _stored(V2, self.team)
        assert _body(V2, self.team)["group_type_mapping"] == {"0": "organization"}
        _create_flag(self.team, "v2-added", BOOLEAN_V2)
        fetch = f"{LEGACY_MODULE}.get_group_types_for_projects"
        failures_before = _v2_counter("posthog_hypercache_sync_total", result="failure")

        with patch(fetch, return_value={self.team.project_id: []}):
            assert update_flag_definitions_v2_cache(self.team) is False
        with patch(fetch, side_effect=GroupTypesUnavailable([self.team.project_id])):
            assert update_flag_definitions_v2_cache(self.team) is False

        assert _stored(V2, self.team) == before
        # The legacy rebuild reports both conditions, so neither counts as a v2 failure.
        assert _v2_counter("posthog_hypercache_sync_total", result="failure") == failures_before


@override_settings(FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=0)
class TestDefinitionsV2Upkeep(DefinitionsV2TestCase):
    def _verify_and_fix(self) -> VerificationResult:
        return verify_and_fix_all_teams(
            config=FLAG_DEFINITIONS_V2_HYPERCACHE_MANAGEMENT_CONFIG,
            verify_team_fn=verify_team_flag_definitions_v2,
            cache_type=FLAG_DEFINITIONS_V2_CACHE_TYPE,
        )

    def test_verify_reports_each_state_of_the_entry(self) -> None:
        other = self._other_team()
        _create_flag(other, "alpha", V1_FILTERS)
        assert verify_team_flag_definitions_v2(other)["status"] == "match"

        self._create_v2_flags()
        assert verify_team_flag_definitions_v2(self.team)["issue"] == "CACHE_MISS"
        self._rebuild()
        assert verify_team_flag_definitions_v2(self.team)["status"] == "match"
        _create_flag(self.team, "v2-added", BOOLEAN_V2)
        mismatch = verify_team_flag_definitions_v2(self.team)
        assert mismatch["issue"] == "DATA_MISMATCH"
        assert _keys(mismatch["db_data"]) == ["v2-added", "v2-boolean", "v2-experiment", "v2-inactive"]

    def test_verification_repairs_holders_and_tracked_teams_only(self) -> None:
        self._create_v2_flags()
        stale = self._other_team("Stale")
        stale_flag = _create_flag(stale, "v2-boolean", BOOLEAN_V2)
        self._rebuild(stale)
        FeatureFlag.objects_including_soft_deleted.filter(pk=stale_flag.pk).delete()
        untouched = self._other_team("Legacy only")
        _create_flag(untouched, "alpha", V1_FILTERS)

        result = self._verify_and_fix()

        assert (result.total, result.cache_miss_fixed, result.cache_mismatch_fixed) == (2, 1, 1)
        assert _keys(_body(V2, self.team)) == ["v2-boolean", "v2-experiment", "v2-inactive"]
        assert _tracked_score(self.team) is not None
        assert _stored(V2, stale) == ABSENT
        assert _stored(V2, untouched) == ABSENT
        assert self._verify_and_fix().total_fixed == 0

    def test_refresh_restamps_the_expiry_of_a_tracked_entry(self) -> None:
        self._create_v2_flags()
        assert update_flag_definitions_v2_cache(self.team, ttl=120) is True
        first_score = _tracked_score(self.team)
        assert first_score is not None and first_score <= time.time() + 120

        counts = cache_expiry_manager.refresh_expiring_caches(
            config=FLAG_DEFINITIONS_V2_HYPERCACHE_MANAGEMENT_CONFIG, ttl_threshold_hours=1, limit=10
        )

        assert (counts.successful, counts.failed) == (1, 0)
        refreshed_score = _tracked_score(self.team)
        assert refreshed_score is not None and refreshed_score >= time.time() + 0.6 * V2.cache_ttl

    def test_cleanup_deletes_the_entry_of_a_deleted_team(self) -> None:
        gone = self._other_team("Gone")
        _create_flag(gone, "v2-boolean", BOOLEAN_V2)
        self._rebuild(gone)
        FeatureFlag.objects_including_soft_deleted.filter(team=gone).delete()
        Team.objects.filter(pk=gone.pk).delete()

        removed = cache_expiry_manager.cleanup_stale_expiry_tracking(FLAG_DEFINITIONS_V2_HYPERCACHE_MANAGEMENT_CONFIG)

        assert removed == 1
        assert _stored(V2, gone) == ABSENT
        assert _tracked_score(gone) is None

    def test_upkeep_task_repairs_a_missing_entry(self) -> None:
        self._create_v2_flags()

        maintain_flag_definitions_v2_cache_entries()

        assert _keys(_body(V2, self.team)) == ["v2-boolean", "v2-experiment", "v2-inactive"]

    def test_upkeep_task_skips_while_another_run_holds_the_lock(self) -> None:
        self._create_v2_flags()
        lock_key = "posthog:flag_definitions_v2_cache_upkeep:lock"
        django_cache.add(lock_key, "locked", timeout=60)
        self.addCleanup(django_cache.delete, lock_key)

        maintain_flag_definitions_v2_cache_entries()

        assert _stored(V2, self.team) == ABSENT
