from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.feature_flags.backend.api.staff_cache import MAX_TEAMS_PER_MUTATION, READABLE_CACHE_CHOICES
from products.feature_flags.backend.flags_cache import flags_hypercache
from products.feature_flags.backend.local_evaluation import (
    flag_definitions_hypercache,
    flag_definitions_without_cohorts_hypercache,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

REBUILD_URL = "/api/feature_flags_staff_cache/rebuild/"
CLEAR_URL = "/api/feature_flags_staff_cache/clear/"
ENTRY_URL = "/api/feature_flags_staff_cache/entry/"


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

    def test_status_reports_the_two_definitions_variants_independently(self):
        self.addCleanup(flag_definitions_hypercache.clear_cache, self.team)
        self.addCleanup(flag_definitions_without_cohorts_hypercache.clear_cache, self.team)

        # Only warm the without-cohorts variant; the with-cohorts variant stays cold.
        flag_definitions_without_cohorts_hypercache.update_cache(self.team)

        response = self.client.get(f"/api/feature_flags_staff_cache/?team_ids={self.team.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"][0]
        self.assertEqual(results["definitions_no_cohorts"]["source"], "redis")
        self.assertEqual(results["definitions"]["source"], "miss")

    @parameterized.expand(
        [
            ("evaluation", flags_hypercache),
            ("definitions", flag_definitions_hypercache),
            ("definitions_no_cohorts", flag_definitions_without_cohorts_hypercache),
        ]
    )
    def test_entry_reads_the_hypercache_matching_the_cache_param(self, cache_kind, hypercache):
        # self.team is shared across every test in this class (setUpTestData), and Redis writes
        # aren't rolled back between tests like the DB is, so clean up this team's Redis entries
        # regardless of how the test ends.
        self.addCleanup(flags_hypercache.clear_cache, self.team)
        self.addCleanup(flag_definitions_hypercache.clear_cache, self.team)
        self.addCleanup(flag_definitions_without_cohorts_hypercache.clear_cache, self.team)

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
