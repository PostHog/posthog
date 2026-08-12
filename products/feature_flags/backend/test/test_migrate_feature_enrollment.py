from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.test.persons import create_person

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.tasks import migrate_feature_enrollment_on_key_change

ENROLLMENT_FILTERS = {
    "feature_enrollment": True,
    "groups": [{"properties": [], "rollout_percentage": 100}],
}


# Person rows land in ClickHouse, which isn't rolled back between tests, so each test
# below uses its own enrollment key and distinct ids to stay order-independent.
def _sent_enrollments(mock_capture: MagicMock) -> dict[str, dict]:
    return {
        event["distinct_id"]: event["properties"]
        for call in mock_capture.call_args_list
        for event in call.kwargs["events"]
    }


class TestMigrateFeatureEnrollmentOnKeyChange(APIBaseTest):
    @patch("products.feature_flags.backend.tasks.capture_batch_internal")
    def test_copies_enrollment_values_without_clobbering(self, mock_capture: MagicMock) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team, key="new-key", created_by=self.user, filters=ENROLLMENT_FILTERS
        )
        create_person(
            team=self.team,
            distinct_ids=["copy-opted-in"],
            properties={"$feature_enrollment/copy-key": True},
        )
        create_person(
            team=self.team,
            distinct_ids=["copy-opted-out"],
            properties={"$feature_enrollment/copy-key": False},
        )
        create_person(
            team=self.team,
            distinct_ids=["copy-already-migrated"],
            properties={"$feature_enrollment/copy-key": True, "$feature_enrollment/new-key": False},
        )
        create_person(team=self.team, distinct_ids=["copy-unrelated"], properties={})

        migrate_feature_enrollment_on_key_change(self.team.id, "copy-key", flag.id)

        assert mock_capture.call_count == 1
        assert _sent_enrollments(mock_capture) == {
            "copy-opted-in": {"$set_once": {"$feature_enrollment/new-key": True}},
            "copy-opted-out": {"$set_once": {"$feature_enrollment/new-key": False}},
        }
        kwargs = mock_capture.call_args.kwargs
        assert kwargs["token"] == self.team.api_token
        assert kwargs["event_source"] == "feature_flag_enrollment_key_migration"
        assert kwargs["process_person_profile"] is True

    @patch("products.feature_flags.backend.tasks.capture_batch_internal")
    def test_writes_to_the_flags_current_key_after_a_chained_rename(self, mock_capture: MagicMock) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team, key="newest-key", created_by=self.user, filters=ENROLLMENT_FILTERS
        )
        create_person(
            team=self.team,
            distinct_ids=["chained-opted-in"],
            properties={"$feature_enrollment/chained-key": True},
        )

        migrate_feature_enrollment_on_key_change(self.team.id, "chained-key", flag.id)

        assert _sent_enrollments(mock_capture) == {
            "chained-opted-in": {"$set_once": {"$feature_enrollment/newest-key": True}}
        }

    @patch("products.feature_flags.backend.tasks.capture_batch_internal")
    def test_no_migration_when_flag_is_gone(self, mock_capture: MagicMock) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team, key="new-key", created_by=self.user, filters=ENROLLMENT_FILTERS, deleted=True
        )
        create_person(
            team=self.team,
            distinct_ids=["deleted-flag-opted-in"],
            properties={"$feature_enrollment/deleted-flag-key": True},
        )

        migrate_feature_enrollment_on_key_change(self.team.id, "deleted-flag-key", flag.id)

        mock_capture.assert_not_called()

    @patch("products.feature_flags.backend.tasks.ENROLLMENT_MIGRATION_PAGE_SIZE", 1)
    @patch("products.feature_flags.backend.tasks.capture_batch_internal")
    def test_pages_through_enrollees(self, mock_capture: MagicMock) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team, key="new-key", created_by=self.user, filters=ENROLLMENT_FILTERS
        )
        create_person(
            team=self.team,
            distinct_ids=["paged-first"],
            properties={"$feature_enrollment/paged-key": True},
        )
        create_person(
            team=self.team,
            distinct_ids=["paged-second"],
            properties={"$feature_enrollment/paged-key": True},
        )

        migrate_feature_enrollment_on_key_change(self.team.id, "paged-key", flag.id)

        assert mock_capture.call_count == 2
        assert _sent_enrollments(mock_capture) == {
            "paged-first": {"$set_once": {"$feature_enrollment/new-key": True}},
            "paged-second": {"$set_once": {"$feature_enrollment/new-key": True}},
        }

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
        mock_delay.assert_called_once_with(self.team.id, "old-key", flag.id)

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
