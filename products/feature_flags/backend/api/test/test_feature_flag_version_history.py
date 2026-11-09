from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import ActivityLog

from products.approvals.backend.models import ApprovalPolicy, ChangeRequest
from products.approvals.backend.services import ChangeRequestService
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.version_history import RECONSTRUCTABLE_FIELDS, RESTORABLE_FIELDS


class TestFeatureFlagVersionHistoryAPI(APIBaseTest):
    def _create_remote_config_flag(self, *, encrypted: bool = False) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="ios-minimum-version",
            name="Minimum app version required",
            active=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {"true": '"1.0.0"'},
            },
            is_remote_configuration=True,
            has_encrypted_payloads=encrypted,
            version=1,
        )

    def test_plaintext_remote_config_flag_returns_historical_payload(self):
        flag = self._create_remote_config_flag()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {"true": '"2.0.0"'},
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/versions/1/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["is_historical"])
        # The point of reconstruction: the payload served at the time, not the current one.
        self.assertEqual(payload["filters"]["payloads"], {"true": '"1.0.0"'})

    def test_encrypted_payload_flag_is_refused(self):
        flag = self._create_remote_config_flag(encrypted=True)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/versions/1/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("filters", response.json())

    def test_version_encrypted_before_downgrade_is_refused(self):
        ciphertext = "gAAAAA-ciphertext-sentinel"
        flag = self._create_remote_config_flag(encrypted=True)
        flag.filters = {
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "payloads": {"true": ciphertext},
        }
        flag.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"has_encrypted_payloads": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        flag.refresh_from_db()
        self.assertFalse(flag.has_encrypted_payloads)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/versions/1/")

        # The live row is plaintext now, but version 1 still holds ciphertext in the activity log.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn(ciphertext, response.content.decode())


ORIGINAL_FILTERS: dict[str, Any] = {
    "groups": [
        {"properties": [{"key": "email", "type": "person", "value": "@example.com"}], "rollout_percentage": 50},
    ],
    "multivariate": {
        "variants": [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
    },
}

BAD_EDIT_FILTERS: dict[str, Any] = {
    "groups": [{"properties": [], "rollout_percentage": 0}],
    "multivariate": {
        "variants": [{"key": "control", "rollout_percentage": 100}, {"key": "test", "rollout_percentage": 0}]
    },
}


def targeting(filters: dict) -> tuple:
    return (
        [(group["properties"], group["rollout_percentage"]) for group in filters["groups"]],
        filters["multivariate"],
    )


class TestFeatureFlagRestoreVersionAPI(APIBaseTest):
    def _flag_with_a_bad_edit(self) -> FeatureFlag:
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="checkout-redesign",
            name="Checkout redesign",
            active=True,
            filters=ORIGINAL_FILTERS,
            version=1,
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"filters": BAD_EDIT_FILTERS, "name": "Checkout redesign, paused", "key": "checkout-redesign-v2"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        flag.refresh_from_db()
        assert flag.version == 2
        return flag

    def _restore(self, flag: FeatureFlag, version_number: int, body: dict) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/versions/{version_number}/restore/",
            body,
            format="json",
        )

    def _gate_flag_updates_on_approval(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}
        ]
        self.organization.save()
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def test_restorable_fields_are_all_reconstructed(self):
        # A restorable field the rebuild does not track would be written back as the current value.
        assert RESTORABLE_FIELDS <= RECONSTRUCTABLE_FIELDS

    def test_restore_sets_configuration_back_and_keeps_key_and_enabled_state(self):
        flag = self._flag_with_a_bad_edit()
        FeatureFlag.objects.filter(pk=flag.pk).update(active=False)

        response = self._restore(flag, 1, {"version": 2})

        assert response.status_code == status.HTTP_200_OK, response.content
        flag.refresh_from_db()
        assert targeting(flag.filters) == targeting(ORIGINAL_FILTERS)
        assert flag.name == "Checkout redesign"
        # The old key may be taken by another flag, and SDKs call the flag by its current one.
        assert flag.key == "checkout-redesign-v2"
        assert flag.active is False
        assert flag.version == 3
        entry = ActivityLog.objects.filter(scope="FeatureFlag", item_id=str(flag.id)).latest("created_at")
        assert entry.detail["trigger"]["job_type"] == "version_restore"
        assert entry.detail["trigger"]["payload"] == {"restored_from_version": 1}

    def test_restored_version_can_itself_be_restored_away(self):
        flag = self._flag_with_a_bad_edit()
        assert self._restore(flag, 1, {"version": 2}).status_code == status.HTTP_200_OK

        response = self._restore(flag, 2, {"version": 3})

        assert response.status_code == status.HTTP_200_OK, response.content
        flag.refresh_from_db()
        assert targeting(flag.filters) == targeting(BAD_EDIT_FILTERS)
        assert flag.version == 4

    def test_stale_version_is_refused_and_writes_nothing(self):
        flag = self._flag_with_a_bad_edit()

        response = self._restore(flag, 1, {"version": 1})

        assert response.status_code == status.HTTP_409_CONFLICT, response.content
        flag.refresh_from_db()
        assert flag.version == 2
        assert targeting(flag.filters) == targeting(BAD_EDIT_FILTERS)

    def test_restoring_the_current_configuration_writes_nothing(self):
        flag = self._flag_with_a_bad_edit()

        response = self._restore(flag, 2, {"version": 2})

        assert response.status_code == status.HTTP_200_OK, response.content
        flag.refresh_from_db()
        assert flag.version == 2

    @parameterized.expand(
        [
            ("archived", {"archived": True, "active": False}, 1, status.HTTP_400_BAD_REQUEST),
            (
                "encrypted_payloads",
                {"has_encrypted_payloads": True, "is_remote_configuration": True},
                1,
                status.HTTP_400_BAD_REQUEST,
            ),
            ("unknown_version", {}, 9, status.HTTP_404_NOT_FOUND),
        ]
    )
    def test_refused_restores_write_nothing(self, _name, flag_state, version_number, expected_status):
        flag = self._flag_with_a_bad_edit()
        FeatureFlag.objects.filter(pk=flag.pk).update(**flag_state)

        response = self._restore(flag, version_number, {"version": 2})

        assert response.status_code == expected_status, response.content
        flag.refresh_from_db()
        assert flag.version == 2
        assert targeting(flag.filters) == targeting(BAD_EDIT_FILTERS)

    @patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
    def test_approval_policy_opens_a_change_request_that_applies_the_restore(self, _mock_enabled):
        flag = self._flag_with_a_bad_edit()
        self._gate_flag_updates_on_approval()

        response = self._restore(flag, 1, {"version": 2})

        assert response.status_code == status.HTTP_409_CONFLICT, response.content
        flag.refresh_from_db()
        assert targeting(flag.filters) == targeting(BAD_EDIT_FILTERS)
        change_request = ChangeRequest.objects.get(team=self.team)
        assert ChangeRequestService(change_request, self.user).approve().status == "applied"
        flag.refresh_from_db()
        assert targeting(flag.filters) == targeting(ORIGINAL_FILTERS)
        assert flag.key == "checkout-redesign-v2"
