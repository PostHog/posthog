from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, call, patch

from parameterized import parameterized
from rest_framework import status

from posthog.test.persons import create_person

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.tasks import migrate_feature_enrollment_on_key_change

ENROLLMENT_FILTERS = {
    "feature_enrollment": True,
    "groups": [{"properties": [], "rollout_percentage": 100}],
}


class TestMigrateFeatureEnrollmentOnKeyChange(APIBaseTest):
    @patch("products.feature_flags.backend.tasks.capture_internal")
    def test_copies_enrollment_values_without_clobbering(self, mock_capture: MagicMock) -> None:
        create_person(
            team=self.team,
            distinct_ids=["opted-in"],
            properties={"$feature_enrollment/old-key": True},
        )
        create_person(
            team=self.team,
            distinct_ids=["opted-out"],
            properties={"$feature_enrollment/old-key": False},
        )
        create_person(
            team=self.team,
            distinct_ids=["already-migrated"],
            properties={"$feature_enrollment/old-key": True, "$feature_enrollment/new-key": False},
        )
        create_person(team=self.team, distinct_ids=["unrelated"], properties={})

        migrate_feature_enrollment_on_key_change(self.team.id, "old-key", "new-key")

        assert mock_capture.call_count == 2
        mock_capture.assert_has_calls(
            [
                call(
                    token=self.team.api_token,
                    event_name="$set",
                    event_source="feature_flag_enrollment_key_migration",
                    distinct_id="opted-in",
                    properties={"$set": {"$feature_enrollment/new-key": True}},
                    process_person_profile=True,
                ),
                call(
                    token=self.team.api_token,
                    event_name="$set",
                    event_source="feature_flag_enrollment_key_migration",
                    distinct_id="opted-out",
                    properties={"$set": {"$feature_enrollment/new-key": False}},
                    process_person_profile=True,
                ),
            ],
            any_order=True,
        )

    @patch("products.feature_flags.backend.tasks.migrate_feature_enrollment_on_key_change.delay")
    def test_key_rename_of_enrollment_flag_enqueues_migration(self, mock_delay: MagicMock) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team, key="old-key", created_by=self.user, filters=ENROLLMENT_FILTERS
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"key": "new-key"},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_delay.assert_called_once_with(self.team.id, "old-key", "new-key")

    @parameterized.expand(
        [
            ("no_enrollment", {"groups": [{"properties": [], "rollout_percentage": 100}]}, {"key": "new-key"}),
            ("no_key_change", ENROLLMENT_FILTERS, {"name": "renamed display name"}),
        ]
    )
    @patch("products.feature_flags.backend.tasks.migrate_feature_enrollment_on_key_change.delay")
    def test_no_migration_when_not_an_enrollment_key_rename(
        self, _name: str, filters: dict, patch_body: dict, mock_delay: MagicMock
    ) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="old-key", created_by=self.user, filters=filters)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            patch_body,
        )

        assert response.status_code == status.HTTP_200_OK
        mock_delay.assert_not_called()
