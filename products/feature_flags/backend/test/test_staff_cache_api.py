import json
import time

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.core.cache import caches
from django.http import QueryDict
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS

from products.feature_flags.backend.api.staff_cache import (
    MAX_TEAMS_PER_MUTATION,
    READABLE_CACHE_CHOICES,
    WARM_RUN_CANCEL_CACHE_KEY,
    WARM_RUN_STATUS_CACHE_KEY,
    StaffCacheStatusQuerySerializer,
)
from products.feature_flags.backend.flags_cache import flags_hypercache
from products.feature_flags.backend.local_evaluation import flag_definitions_hypercache
from products.feature_flags.backend.models.feature_flag import FeatureFlag

REBUILD_URL = "/api/feature_flags_staff_cache/rebuild/"
CLEAR_URL = "/api/feature_flags_staff_cache/clear/"
ENTRY_URL = "/api/feature_flags_staff_cache/entry/"
WARM_RUN_URL = "/api/feature_flags_staff_cache/warm_run/"
WARM_RUN_CANCEL_URL = "/api/feature_flags_staff_cache/warm_run/cancel/"


def _called_once_with(mock, team_id):
    mock.assert_called_once_with(team_id)


def _delay_called_once_with(mock, team_id):
    mock.delay.assert_called_once_with(team_id)


# (label, url, evaluation patch target, definitions task name, evaluation-call assertion) - rebuild
# and clear share the same enqueue/found-not-found shape. Rebuild's evaluation cache goes through
# `enqueue_evaluation_cache_invalidation` directly (the same signal an organic flag change raises),
# while everything else still goes through a plain Celery `.delay()`.
MUTATION_CASES = [
    ("rebuild", REBUILD_URL, "enqueue_evaluation_cache_invalidation", "update_team_flags_cache", _called_once_with),
    ("clear", CLEAR_URL, "clear_team_evaluation_cache", "clear_team_definitions_cache", _delay_called_once_with),
]


class TestFeatureFlagsStaffCacheAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def test_non_staff_user_gets_403_on_all_actions(self):
        self.user.is_staff = False
        self.user.save()

        status_response = self.client.get(f"/api/feature_flags_staff_cache/?team_ids={self.team.id}")
        self.assertEqual(status_response.status_code, status.HTTP_403_FORBIDDEN)

        rebuild_response = self.client.post(REBUILD_URL, {"team_ids": [self.team.id]}, format="json")
        self.assertEqual(rebuild_response.status_code, status.HTTP_403_FORBIDDEN)

        clear_response = self.client.post(CLEAR_URL, {"team_ids": [self.team.id]}, format="json")
        self.assertEqual(clear_response.status_code, status.HTTP_403_FORBIDDEN)

        entry_response = self.client.get(ENTRY_URL, {"team_id": str(self.team.id), "cache": "evaluation"})
        self.assertEqual(entry_response.status_code, status.HTTP_403_FORBIDDEN)

        warm_run_response = self.client.get(WARM_RUN_URL)
        self.assertEqual(warm_run_response.status_code, status.HTTP_403_FORBIDDEN)

        cancel_response = self.client.post(WARM_RUN_CANCEL_URL)
        self.assertEqual(cancel_response.status_code, status.HTTP_403_FORBIDDEN)

    @parameterized.expand(MUTATION_CASES)
    def test_mutation_enqueues_both_tasks_and_returns_202(
        self, _name, url, evaluation_target, definitions_task, assert_evaluation_called
    ):
        with (
            patch(f"products.feature_flags.backend.api.staff_cache.{evaluation_target}") as mock_evaluation,
            patch(f"products.feature_flags.backend.api.staff_cache.{definitions_task}") as mock_definitions,
        ):
            response = self.client.post(url, {"team_ids": [self.team.id]}, format="json")
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

            self.assertEqual(response.json()["queued_team_ids"], [self.team.id])
            self.assertEqual(response.json()["not_found_team_ids"], [])
            assert_evaluation_called(mock_evaluation, self.team.id)
            mock_definitions.delay.assert_called_once_with(self.team.id)

    @parameterized.expand(MUTATION_CASES)
    def test_mutation_respects_caches_filter(
        self, _name, url, evaluation_target, definitions_task, assert_evaluation_called
    ):
        with (
            patch(f"products.feature_flags.backend.api.staff_cache.{evaluation_target}") as mock_evaluation,
            patch(f"products.feature_flags.backend.api.staff_cache.{definitions_task}") as mock_definitions,
        ):
            response = self.client.post(url, {"team_ids": [self.team.id], "caches": ["evaluation"]}, format="json")
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

            assert_evaluation_called(mock_evaluation, self.team.id)
            mock_definitions.delay.assert_not_called()

    @parameterized.expand(MUTATION_CASES)
    def test_mutation_reports_unknown_team_ids(
        self, _name, url, evaluation_target, definitions_task, assert_evaluation_called
    ):
        missing_id = self.team.id + 9999
        with (
            patch(f"products.feature_flags.backend.api.staff_cache.{evaluation_target}") as mock_evaluation,
            patch(f"products.feature_flags.backend.api.staff_cache.{definitions_task}"),
        ):
            response = self.client.post(url, {"team_ids": [self.team.id, missing_id]}, format="json")
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

            self.assertEqual(response.json()["queued_team_ids"], [self.team.id])
            self.assertEqual(response.json()["not_found_team_ids"], [missing_id])
            assert_evaluation_called(mock_evaluation, self.team.id)

    def test_rebuild_over_max_team_ids_returns_400(self):
        team_ids = list(range(1, MAX_TEAMS_PER_MUTATION + 2))
        response = self.client.post(REBUILD_URL, {"team_ids": team_ids}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_status_reflects_real_cache_state(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="status-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        flags_hypercache.update_cache(self.team)
        warm = self.client.get(f"/api/feature_flags_staff_cache/?team_ids={self.team.id}")
        self.assertEqual(warm.status_code, status.HTTP_200_OK)
        evaluation = warm.json()["results"][0]["evaluation"]
        self.assertEqual(evaluation["source"], "redis")
        self.assertEqual(evaluation["flag_count"], 1)

        flags_hypercache.clear_cache(self.team)
        cold = self.client.get(f"/api/feature_flags_staff_cache/?team_ids={self.team.id}")
        self.assertEqual(cold.json()["results"][0]["evaluation"]["source"], "miss")

    def test_status_dedupes_repeated_team_ids(self):
        # A caller passing the same team id twice (e.g. ?team_ids=1&team_ids=1) should get one
        # row back, not a duplicate per repetition.
        response = self.client.get(f"/api/feature_flags_staff_cache/?team_ids={self.team.id}&team_ids={self.team.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

    @parameterized.expand(
        [
            ("evaluation", flags_hypercache),
            ("definitions", flag_definitions_hypercache),
        ]
    )
    def test_entry_reads_the_hypercache_matching_the_cache_param(self, cache_kind, hypercache):
        # self.team is shared across every test in this class (setUpTestData), and Redis writes
        # aren't rolled back between tests like the DB is, so clean up this team's Redis entries
        # regardless of how the test ends.
        self.addCleanup(flags_hypercache.clear_cache, self.team)
        self.addCleanup(flag_definitions_hypercache.clear_cache, self.team)

        FeatureFlag.objects.create(
            team=self.team,
            key="entry-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        hypercache.update_cache(self.team)

        warm = self.client.get(ENTRY_URL, {"team_id": str(self.team.id), "cache": cache_kind})
        self.assertEqual(warm.status_code, status.HTTP_200_OK)
        self.assertEqual(warm.json()["source"], "redis")
        self.assertEqual(len(warm.json()["data"]["flags"]), 1)

        # Any kind other than the one just warmed should still be cold.
        other_kind = next(kind for kind in READABLE_CACHE_CHOICES if kind != cache_kind)
        cold = self.client.get(ENTRY_URL, {"team_id": str(self.team.id), "cache": other_kind})
        self.assertEqual(cold.json()["source"], "miss")
        self.assertIsNone(cold.json()["data"])

    def test_entry_reports_miss_for_a_warm_empty_sentinel(self):
        # A prior write that cached "nothing to see here" (e.g. a team with zero flags) stores
        # the empty sentinel in redis rather than an actual miss. entry() should report that the
        # same way list()'s _entry_status does: as a miss, not as a redis hit with null data.
        self.addCleanup(flags_hypercache.clear_cache, self.team)
        flags_hypercache.set_cache_value(self.team, None)

        response = self.client.get(ENTRY_URL, {"team_id": str(self.team.id), "cache": "evaluation"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["source"], "miss")
        self.assertIsNone(response.json()["data"])

    def test_entry_returns_404_for_unknown_team(self):
        missing_id = self.team.id + 9999
        response = self.client.get(ENTRY_URL, {"team_id": str(missing_id), "cache": "evaluation"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestTeamIdsFieldQueryParamFormats(SimpleTestCase):
    # Our generated TS client (and plain URLSearchParams) serializes a number[] query param as one
    # comma-joined value rather than repeated keys. If `_team_ids_field` ever reverts to a plain
    # `serializers.ListField`, the comma-separated case starts failing validation while the
    # repeated-keys case keeps passing, silently breaking every caller that uses the generated
    # client against a team_ids-backed query endpoint.
    @parameterized.expand(
        [
            ("repeated_keys", "team_ids=1&team_ids=2"),
            ("comma_separated", "team_ids=1,2"),
        ]
    )
    def test_accepts_both_repeated_and_comma_separated_team_ids(self, _name, query_string):
        serializer = StaffCacheStatusQuerySerializer(data=QueryDict(query_string))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["team_ids"], [1, 2])


def _warm_run_blob(**overrides):
    blob = {
        "run_id": "run-1",
        "state": "running",
        "scope": "teams_with_flags",
        "total": 100,
        "processed": 40,
        "successful": 39,
        "failed": 1,
        "last_team_id": 4321,
        "started_at": int(time.time()) - 60,
        "updated_at": int(time.time()),
    }
    blob.update(overrides)
    return json.dumps(blob)


# Blobs the reader must tolerate (treat as "no run") rather than 500 the staff page:
# a newer/older warmer binary could write a shape this code doesn't know.
MALFORMED_STATUS_BLOBS = [
    ("not_json", "{nope"),
    ("not_a_dict", json.dumps([1, 2])),
    ("missing_run_id", json.dumps({"state": "running"})),
    ("unknown_state", json.dumps({"run_id": "x", "state": "exploded"})),
]

_CACHES_WITH_FLAGS_DEDICATED = {
    **settings.CACHES,
    FLAGS_DEDICATED_CACHE_ALIAS: {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "flags-dedicated-staff-warm-run-tests",
    },
}


@override_settings(CACHES=_CACHES_WITH_FLAGS_DEDICATED)
class TestFeatureFlagsStaffWarmRunAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.cache = caches[FLAGS_DEDICATED_CACHE_ALIAS]
        self.cache.clear()

    def test_returns_null_run_when_no_status_recorded(self):
        response = self.client.get(WARM_RUN_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["run"])

    def test_handles_missing_dedicated_cache_config(self):
        # Self-hosted instances without FLAGS_REDIS_URL have no flags_dedicated cache alias;
        # the endpoints must degrade instead of KeyError-ing into a 500.
        caches_without = {k: v for k, v in settings.CACHES.items() if k != FLAGS_DEDICATED_CACHE_ALIAS}
        with override_settings(CACHES=caches_without):
            get_response = self.client.get(WARM_RUN_URL)
            self.assertEqual(get_response.status_code, status.HTTP_200_OK)
            self.assertIsNone(get_response.json()["run"])

            cancel_response = self.client.post(WARM_RUN_CANCEL_URL)
            self.assertEqual(cancel_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reports_fresh_running_run(self):
        self.cache.set(WARM_RUN_STATUS_CACHE_KEY, _warm_run_blob())

        run = self.client.get(WARM_RUN_URL).json()["run"]
        self.assertEqual(run["run_id"], "run-1")
        self.assertEqual(run["state"], "running")
        self.assertEqual(run["scope"], "teams_with_flags")
        self.assertEqual(run["total"], 100)
        self.assertEqual(run["processed"], 40)
        self.assertEqual(run["successful"], 39)
        self.assertEqual(run["failed"], 1)
        self.assertEqual(run["last_team_id"], 4321)
        self.assertFalse(run["is_stale"])
        self.assertFalse(run["cancel_requested"])

    def test_running_run_with_dead_heartbeat_is_stale(self):
        self.cache.set(WARM_RUN_STATUS_CACHE_KEY, _warm_run_blob(updated_at=int(time.time()) - 600))
        run = self.client.get(WARM_RUN_URL).json()["run"]
        self.assertTrue(run["is_stale"])

    def test_terminal_run_with_old_heartbeat_is_not_stale(self):
        self.cache.set(
            WARM_RUN_STATUS_CACHE_KEY,
            _warm_run_blob(state="completed", updated_at=int(time.time()) - 600),
        )
        run = self.client.get(WARM_RUN_URL).json()["run"]
        self.assertFalse(run["is_stale"])

    def test_cancel_requested_reflects_only_a_matching_cancel_key(self):
        self.cache.set(WARM_RUN_STATUS_CACHE_KEY, _warm_run_blob())

        self.cache.set(WARM_RUN_CANCEL_CACHE_KEY, "some-older-run")
        run = self.client.get(WARM_RUN_URL).json()["run"]
        self.assertFalse(run["cancel_requested"])

        self.cache.set(WARM_RUN_CANCEL_CACHE_KEY, "run-1")
        run = self.client.get(WARM_RUN_URL).json()["run"]
        self.assertTrue(run["cancel_requested"])

    def test_cancel_writes_run_scoped_cancel_key(self):
        # The warmer only honors a cancel key whose value equals its own run id, so the
        # endpoint must write exactly the running run's id.
        self.cache.set(WARM_RUN_STATUS_CACHE_KEY, _warm_run_blob())

        response = self.client.post(WARM_RUN_CANCEL_URL)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.json(), {"run_id": "run-1", "cancel_requested": True})
        self.assertEqual(self.cache.get(WARM_RUN_CANCEL_CACHE_KEY), "run-1")

    @parameterized.expand(
        [
            ("no_run_recorded", None),
            ("terminal_run", "completed"),
        ]
    )
    def test_cancel_rejected_when_nothing_is_running(self, _name, state):
        if state is not None:
            self.cache.set(WARM_RUN_STATUS_CACHE_KEY, _warm_run_blob(state=state))

        response = self.client.post(WARM_RUN_CANCEL_URL)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNone(self.cache.get(WARM_RUN_CANCEL_CACHE_KEY))

    @parameterized.expand(MALFORMED_STATUS_BLOBS)
    def test_malformed_status_blob_reads_as_no_run(self, _name, raw):
        self.cache.set(WARM_RUN_STATUS_CACHE_KEY, raw)

        response = self.client.get(WARM_RUN_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["run"])
