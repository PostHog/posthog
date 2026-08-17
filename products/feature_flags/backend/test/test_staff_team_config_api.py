from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.feature_flags.backend.api.staff_team_config import (
    MAX_TEAM_IDS_PER_QUERY,
    StaffTeamConfigMutationSerializer,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.team_feature_flags_config import (
    MAX_FEATURE_FLAGS_OVERRIDE_CEILING,
    TeamFeatureFlagsConfig,
)

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
        config.max_feature_flags_override = 5000
        config.save(update_fields=["minimal_flag_called_events", "max_feature_flags_override"])
        FeatureFlag.objects.create(team=other_team, created_by=self.user, key="other-1", filters={"groups": []})
        FeatureFlag.objects.create(team=other_team, created_by=self.user, key="other-2", filters={"groups": []})

        missing_id = other_team.id + 9999
        response = self.client.get(_list_url([self.team.id, other_team.id, missing_id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = {
            row["team_id"]: (
                row["minimal_flag_called_events"],
                row["max_feature_flags_override"],
                row["effective_max_feature_flags"],
                row["feature_flag_count"],
            )
            for row in response.json()["results"]
        }
        # self.team's row was auto-created (still False, no override) by the team-creation
        # signal; missing_id doesn't correspond to a real team and must not appear at all.
        # other_team's count of 2 (not 0) proves feature_flag_count reflects the real count
        # rather than a hardcoded placeholder.
        self.assertEqual(
            results,
            {
                self.team.id: (False, None, 2000, 0),
                other_team.id: (True, 5000, 5000, 2),
            },
        )

    def test_list_defaults_to_false_when_config_row_is_missing(self):
        # Models a legacy team that predates this extension (no auto-created row). list() must
        # fall back to defaults rather than 500ing on the missing row.
        TeamFeatureFlagsConfig.objects.filter(team=self.team).delete()

        response = self.client.get(_list_url([self.team.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["results"],
            [
                {
                    "team_id": self.team.id,
                    "minimal_flag_called_events": False,
                    "max_feature_flags_override": None,
                    "effective_max_feature_flags": 2000,
                    "feature_flag_count": 0,
                }
            ],
        )

    def test_list_dedupes_repeated_team_ids(self):
        response = self.client.get(_list_url([self.team.id, self.team.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_list_over_max_team_ids_returns_400(self):
        team_ids = list(range(1, MAX_TEAM_IDS_PER_QUERY + 2))
        response = self.client.get(_list_url(team_ids))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand([(True,), (False,)])
    def test_set_updates_db_value_and_enqueues_cache_refresh_tasks(self, new_value):
        with (
            patch("posthog.tasks.team_metadata.update_team_metadata_cache_task") as mock_metadata_task,
            patch("products.feature_flags.backend.tasks.update_team_flags_cache") as mock_flags_task,
        ):
            response = self.client.post(
                SET_URL, {"team_id": self.team.id, "minimal_flag_called_events": new_value}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "team_id": self.team.id,
                "minimal_flag_called_events": new_value,
                "max_feature_flags_override": None,
                "effective_max_feature_flags": 2000,
                "feature_flag_count": 0,
            },
        )

        config = TeamFeatureFlagsConfig.objects.get(team=self.team)
        self.assertEqual(config.minimal_flag_called_events, new_value)
        # /flags and /decide read this value out of team_metadata_hypercache, and local-eval
        # SDKs read it out of the flag-definitions blob — a bare DB write has no effect until
        # both caches are rebuilt.
        mock_metadata_task.delay.assert_called_once_with(self.team.id)
        mock_flags_task.delay.assert_called_once_with(self.team.id)

    def test_set_returns_404_for_unknown_team(self):
        missing_id = self.team.id + 9999
        response = self.client.post(SET_URL, {"team_id": missing_id, "minimal_flag_called_events": True}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_set_creates_config_row_if_missing(self):
        # Exercises the get_or_create_team_extension create branch: don't rely on the
        # auto-created row from the team-creation signal.
        TeamFeatureFlagsConfig.objects.filter(team=self.team).delete()

        with (
            patch("posthog.tasks.team_metadata.update_team_metadata_cache_task"),
            patch("products.feature_flags.backend.tasks.update_team_flags_cache"),
        ):
            response = self.client.post(
                SET_URL, {"team_id": self.team.id, "minimal_flag_called_events": True}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        config = TeamFeatureFlagsConfig.objects.get(team=self.team)
        self.assertTrue(config.minimal_flag_called_events)

    @parameterized.expand(
        [
            (
                "override_only_leaves_minimal_flag_called_events_untouched",
                {"max_feature_flags_override": 5000},
                5000,
                False,
            ),
            (
                "minimal_flag_called_events_only_leaves_override_untouched",
                {"minimal_flag_called_events": True},
                1234,
                True,
            ),
        ]
    )
    def test_set_partial_update_leaves_the_other_setting_untouched(
        self, _name, body, expected_override, expected_minimal_flag_called_events
    ):
        # A naive
        # `config.max_feature_flags_override = validated.get("max_feature_flags_override")` would
        # clear the override to None on every minimal_flag_called_events toggle (and vice versa),
        # since a key absent from the request becomes None under .get(). set() must build
        # update_fields from only the keys actually present in validated_data.
        config = get_or_create_team_extension(self.team, TeamFeatureFlagsConfig)
        config.minimal_flag_called_events = False
        config.max_feature_flags_override = 1234
        config.save(update_fields=["minimal_flag_called_events", "max_feature_flags_override"])

        with (
            patch("posthog.tasks.team_metadata.update_team_metadata_cache_task"),
            patch("products.feature_flags.backend.tasks.update_team_flags_cache"),
        ):
            response = self.client.post(SET_URL, {"team_id": self.team.id, **body}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # The staff table renders this response directly, so returning the pre-save value (the
        # `old_*` local sits in the same scope with a near-identical name) would show a stale
        # limit until reload.
        self.assertEqual(response.json()["max_feature_flags_override"], expected_override)
        self.assertEqual(response.json()["effective_max_feature_flags"], expected_override)
        config.refresh_from_db()
        self.assertEqual(config.max_feature_flags_override, expected_override)
        self.assertEqual(config.minimal_flag_called_events, expected_minimal_flag_called_events)

    def test_set_clears_the_override_when_sent_null(self):
        # DRF gives absent-vs-null three-way semantics for free (required=False, allow_null=True),
        # but only if the view actually distinguishes them. A regression that treats a present
        # `None` the same as an absent key would make the override permanently un-clearable from
        # the UI: the empty-input dialog submits an explicit null to mean "remove the override".
        config = get_or_create_team_extension(self.team, TeamFeatureFlagsConfig)
        config.max_feature_flags_override = 5000
        config.save(update_fields=["max_feature_flags_override"])

        with (
            patch("posthog.tasks.team_metadata.update_team_metadata_cache_task"),
            patch("products.feature_flags.backend.tasks.update_team_flags_cache"),
        ):
            response = self.client.post(
                SET_URL, {"team_id": self.team.id, "max_feature_flags_override": None}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        config.refresh_from_db()
        self.assertIsNone(config.max_feature_flags_override)

    def test_set_does_not_enqueue_cache_tasks_for_an_override_only_write(self):
        # Nothing outside Django reads max_feature_flags_override (the limit is read straight
        # from Postgres on flag create), unlike minimal_flag_called_events which /flags and
        # local-eval SDKs read out of caches. A regression that enqueues the fan-out
        # unconditionally would silently make this write look cache-dependent when it isn't.
        with (
            patch("posthog.tasks.team_metadata.update_team_metadata_cache_task") as mock_metadata_task,
            patch("products.feature_flags.backend.tasks.update_team_flags_cache") as mock_flags_task,
        ):
            response = self.client.post(
                SET_URL, {"team_id": self.team.id, "max_feature_flags_override": 5000}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_metadata_task.delay.assert_not_called()
        mock_flags_task.delay.assert_not_called()

    def test_set_rejects_a_form_encoded_body(self):
        # parser_classes = [JSONParser] is the only thing stopping DRF's default_empty_html from
        # reading an absent minimal_flag_called_events as False on a limit-only write. Every other
        # test here posts JSON, so deleting that line would leave them all green while a real
        # form-encoded request silently switched the setting off.
        config = get_or_create_team_extension(self.team, TeamFeatureFlagsConfig)
        config.minimal_flag_called_events = True
        config.save(update_fields=["minimal_flag_called_events"])

        response = self.client.post(
            SET_URL, {"team_id": self.team.id, "max_feature_flags_override": 5000}, format="multipart"
        )

        # The form body never reaches validated_data at all, which is why team_id reads as missing
        # rather than the request succeeding. Asserting the surviving setting rather than the exact
        # status keeps this pinned to the harm if DRF changes how it signals the rejection.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "team_id")
        config.refresh_from_db()
        self.assertTrue(config.minimal_flag_called_events)

    @parameterized.expand([("a_value", 5000), ("an_explicit_null", None)])
    def test_set_refuses_an_override_on_an_environment_team(self, _name, override):
        # Flags are project-scoped, so get_max_feature_flags_for_team reads the override off the
        # project root. A row written on an environment team would never be read, leaving staff
        # believing they had granted capacity that was silently inert.
        #
        # The null case is refused too, since the guard keys on the field being present rather than
        # on its value. Clearing an override that was never writable here is a no-op, so refusing
        # it costs nothing and keeps one answer for "can this team hold an override?". Pinned so a
        # later `validated.get(...) is not None` refactor can't flip it silently.
        environment = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="Environment"
        )

        response = self.client.post(
            SET_URL, {"team_id": environment.id, "max_feature_flags_override": override}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(str(self.team.id), str(response.json()))
        self.assertIsNone(TeamFeatureFlagsConfig.objects.get(team=environment).max_feature_flags_override)

    def test_list_shows_an_environment_team_its_project_roots_override(self):
        # The override is enforced against the project root, so displaying the environment team's
        # own row (which has none) would show Default while the validator enforces the root's
        # override. list() must resolve the override to the root.
        root_config = get_or_create_team_extension(self.team, TeamFeatureFlagsConfig)
        root_config.max_feature_flags_override = 5000
        root_config.save(update_fields=["max_feature_flags_override"])
        environment = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="Environment"
        )

        response = self.client.get(_list_url([environment.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = response.json()["results"][0]
        self.assertEqual(row["max_feature_flags_override"], 5000)
        self.assertEqual(row["effective_max_feature_flags"], 5000)

    def test_set_response_shows_an_environment_team_its_project_roots_override(self):
        # An environment team reaches set() only on a minimal_flag_called_events-only edit, and its
        # response row still has to show the root's override rather than its own empty one, or the
        # staff table renders Default right after an edit.
        root_config = get_or_create_team_extension(self.team, TeamFeatureFlagsConfig)
        root_config.max_feature_flags_override = 5000
        root_config.save(update_fields=["max_feature_flags_override"])
        environment = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="Environment"
        )

        with (
            patch("posthog.tasks.team_metadata.update_team_metadata_cache_task"),
            patch("products.feature_flags.backend.tasks.update_team_flags_cache"),
        ):
            response = self.client.post(
                SET_URL, {"team_id": environment.id, "minimal_flag_called_events": True}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["max_feature_flags_override"], 5000)
        self.assertEqual(response.json()["effective_max_feature_flags"], 5000)


class TestStaffTeamConfigMutationSerializerBounds(SimpleTestCase):
    # Field-level validation only, no DB, because validating a body never reaches the object-level
    # validate() or the viewset. A regression that drops min_value/max_value from the
    # serializer field (or the neither-field validate() check) would still pass every
    # DB-backed test above, since those all send a body with at least one valid setting.
    @parameterized.expand(
        [
            ("zero_rejected", {"team_id": 1, "max_feature_flags_override": 0}, "max_feature_flags_override"),
            (
                "above_ceiling_rejected",
                {"team_id": 1, "max_feature_flags_override": MAX_FEATURE_FLAGS_OVERRIDE_CEILING + 1},
                "max_feature_flags_override",
            ),
            ("neither_setting_present_rejected", {"team_id": 1}, "non_field_errors"),
        ]
    )
    def test_rejects_invalid_bodies(self, _name, data, expected_error_key):
        serializer = StaffTeamConfigMutationSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        # Asserting the key, not just that validation failed: a bare assertFalse would stay green
        # if the bounds disappeared and some unrelated required field started rejecting these.
        self.assertIn(expected_error_key, serializer.errors)

    def test_accepts_the_ceiling_itself(self):
        # Pins the ceiling as inclusive. Narrowing max_value by one would keep every rejection
        # case above green while refusing the largest grant the constant advertises.
        serializer = StaffTeamConfigMutationSerializer(
            data={"team_id": 1, "max_feature_flags_override": MAX_FEATURE_FLAGS_OVERRIDE_CEILING}
        )
        self.assertTrue(serializer.is_valid())
