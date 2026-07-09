from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.feature_flags.backend.api.staff_team_config import MAX_TEAM_IDS_PER_QUERY
from products.feature_flags.backend.models.team_feature_flags_config import TeamFeatureFlagsConfig

LIST_URL = "/api/feature_flags_staff_team_config/"
SET_URL = "/api/feature_flags_staff_team_config/set/"


def _list_url(team_ids: list[int]) -> str:
    query = "&".join(f"team_ids={team_id}" for team_id in team_ids)
    return f"{LIST_URL}?{query}"


class TestFeatureFlagsStaffTeamConfigAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def test_non_staff_user_gets_403_on_list_and_set(self):
        self.user.is_staff = False
        self.user.save()

        list_response = self.client.get(_list_url([self.team.id]))
        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)

        set_response = self.client.post(
            SET_URL, {"team_id": self.team.id, "minimal_flag_called_events": True}, format="json"
        )
        self.assertEqual(set_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_returns_config_for_existing_teams_and_skips_unknown_ids(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        config = get_or_create_team_extension(other_team, TeamFeatureFlagsConfig)
        config.minimal_flag_called_events = True
        config.save(update_fields=["minimal_flag_called_events"])

        missing_id = other_team.id + 9999
        response = self.client.get(_list_url([self.team.id, other_team.id, missing_id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = {row["team_id"]: row["minimal_flag_called_events"] for row in response.json()["results"]}
        # self.team's row was auto-created (still False) by the team-creation signal; missing_id
        # doesn't correspond to a real team and must not appear at all.
        self.assertEqual(results, {self.team.id: False, other_team.id: True})

    def test_list_defaults_to_false_when_config_row_is_missing(self):
        # Models a legacy team that predates this extension (no auto-created row). list() must
        # fall back to False rather than 500ing on the missing row.
        TeamFeatureFlagsConfig.objects.filter(team=self.team).delete()

        response = self.client.get(_list_url([self.team.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [{"team_id": self.team.id, "minimal_flag_called_events": False}])

    def test_list_dedupes_repeated_team_ids(self):
        response = self.client.get(_list_url([self.team.id, self.team.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_list_over_max_team_ids_returns_400(self):
        team_ids = list(range(1, MAX_TEAM_IDS_PER_QUERY + 2))
        response = self.client.get(_list_url(team_ids))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand([(True,), (False,)])
    def test_set_updates_db_value_and_enqueues_cache_refresh_task(self, new_value):
        with patch("posthog.tasks.team_metadata.update_team_metadata_cache_task") as mock_task:
            response = self.client.post(
                SET_URL, {"team_id": self.team.id, "minimal_flag_called_events": new_value}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"team_id": self.team.id, "minimal_flag_called_events": new_value})

        config = TeamFeatureFlagsConfig.objects.get(team=self.team)
        self.assertEqual(config.minimal_flag_called_events, new_value)
        # /flags and /decide read this value out of team_metadata_hypercache, not the DB, so a
        # bare write has no effect until that cache is rebuilt.
        mock_task.delay.assert_called_once_with(self.team.id)

    def test_set_returns_404_for_unknown_team(self):
        missing_id = self.team.id + 9999
        response = self.client.post(SET_URL, {"team_id": missing_id, "minimal_flag_called_events": True}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_set_creates_config_row_if_missing(self):
        # Exercises the get_or_create_team_extension create branch: don't rely on the
        # auto-created row from the team-creation signal.
        TeamFeatureFlagsConfig.objects.filter(team=self.team).delete()

        with patch("posthog.tasks.team_metadata.update_team_metadata_cache_task"):
            response = self.client.post(
                SET_URL, {"team_id": self.team.id, "minimal_flag_called_events": True}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        config = TeamFeatureFlagsConfig.objects.get(team=self.team)
        self.assertTrue(config.minimal_flag_called_events)
