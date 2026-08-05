from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import serializers, status

from posthog.api.test.test_team import create_team
from posthog.models import User
from posthog.models.organization import OrganizationMembership

from products.feature_flags.backend.api.scheduled_change import ScheduledChangeSerializer
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.scheduled_change import ScheduledChange

from ee.api.rbac.test.test_access_control import BaseAccessControlTest
from ee.models.rbac.access_control import AccessControl


class TestScheduledChange(APIBaseTest):
    def test_can_create_flag_change(self):
        # Create a feature flag to schedule changes for
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="test-flag", name="Test Flag"
        )

        payload = {"field": "active", "value": "false"}

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "id": 6,
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": payload,
                "scheduled_at": "2023-12-08T12:00:00Z",
                "executed_at": None,
                "failure_reason": "",
            },
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert ScheduledChange.objects.filter(id=response_data["id"]).exists()
        assert response_data["model_name"] == "FeatureFlag"
        assert response_data["record_id"] == str(feature_flag.id)
        assert response_data["payload"] == payload
        assert response_data["created_by"]["id"] == self.user.id

    def test_cannot_create_scheduled_change_without_feature_flag_edit_permission(self):
        """Test that users without edit permissions cannot create scheduled changes for feature flags"""
        # Create a feature flag
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="test-flag", name="Test Flag"
        )

        payload = {"operation": "update_status", "value": False}

        # Mock the permission check to return False
        with patch(
            "products.feature_flags.backend.api.scheduled_change.CanEditFeatureFlag.has_object_permission",
            return_value=False,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/scheduled_changes/",
                data={
                    "record_id": str(feature_flag.id),
                    "model_name": "FeatureFlag",
                    "payload": payload,
                    "scheduled_at": "2023-12-08T12:00:00Z",
                },
            )

        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "You don't have edit permissions for this feature flag" in str(response_data)
        assert not ScheduledChange.objects.filter(record_id=str(feature_flag.id)).exists()

    def test_can_create_scheduled_change_with_feature_flag_edit_permission(self):
        """Test that users with edit permissions can create scheduled changes for feature flags"""
        # Create a feature flag
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="test-flag", name="Test Flag"
        )

        payload = {"operation": "update_status", "value": False}

        # Mock the permission check to return True
        with patch(
            "products.feature_flags.backend.api.scheduled_change.CanEditFeatureFlag.has_object_permission",
            return_value=True,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/scheduled_changes/",
                data={
                    "record_id": str(feature_flag.id),
                    "model_name": "FeatureFlag",
                    "payload": payload,
                    "scheduled_at": "2023-12-08T12:00:00Z",
                },
            )

        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert ScheduledChange.objects.filter(record_id=str(feature_flag.id)).exists()
        assert response_data["model_name"] == "FeatureFlag"
        assert response_data["record_id"] == str(feature_flag.id)

    def test_cannot_create_scheduled_change_for_nonexistent_feature_flag(self):
        """Test that scheduled changes cannot be created for non-existent feature flags"""
        payload = {"operation": "update_status", "value": False}

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": "999999",  # Non-existent feature flag ID
                "model_name": "FeatureFlag",
                "payload": payload,
                "scheduled_at": "2023-12-08T12:00:00Z",
            },
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "Feature flag not found" in str(response_data)
        assert not ScheduledChange.objects.filter(record_id="999999").exists()

    def test_cannot_create_scheduled_change_for_non_numeric_record_id(self):
        """A non-numeric record_id is rejected with a 400, not a 500 from the int cast."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": "not-a-number",
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": False},
                "scheduled_at": "2023-12-08T12:00:00Z",
            },
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "Feature flag not found" in str(response_data)
        assert not ScheduledChange.objects.filter(record_id="not-a-number").exists()

    def test_create_canonicalizes_non_canonical_record_id(self):
        """A padded record_id (e.g. leading zeros) resolves to the same flag but must be stored canonically,
        so the viewset's str-equality per-flag access filter keeps matching it."""
        feature_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="canon", name="Canon")

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": f"000{feature_flag.id}",
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": False},
                "scheduled_at": "2023-12-08T12:00:00Z",
            },
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["record_id"] == str(feature_flag.id)
        assert ScheduledChange.objects.get(id=response_data["id"]).record_id == str(feature_flag.id)

    def test_update_canonicalizes_non_canonical_record_id(self):
        """A legacy schedule whose stored record_id has leading zeros is canonicalized on update,
        so the viewset's str-equality per-flag access filter keeps matching it."""
        feature_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="update-canon", name="UC")
        change = ScheduledChange.objects.create(
            team=self.team,
            record_id=f"000{feature_flag.id}",
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at=datetime(2023, 12, 8, 12, 0, 0, tzinfo=UTC),
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/scheduled_changes/{change.id}/",
            data={"scheduled_at": "2023-12-09T12:00:00Z"},
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        change.refresh_from_db()
        assert change.record_id == str(feature_flag.id)

    def test_recurring_schedule_requires_interval(self):
        """Test that recurring schedules require a recurrence_interval"""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="recurring-test-flag", name="Recurring Test Flag"
        )

        payload = {"operation": "update_status", "value": True}

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": payload,
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                # Missing recurrence_interval
            },
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "recurrence_interval" in str(response_data)
        assert "required when is_recurring is true" in str(response_data)

    @parameterized.expand(
        [
            (
                "update_status_allowed",
                "update_status",
                False,
                "daily",
                status.HTTP_201_CREATED,
            ),
            (
                "update_variants_allowed",
                "update_variants",
                {"variants": [{"key": "control", "rollout_percentage": 100}], "payloads": {}},
                "weekly",
                status.HTTP_201_CREATED,
            ),
            (
                "add_release_condition_blocked",
                "add_release_condition",
                {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "daily",
                status.HTTP_400_BAD_REQUEST,
            ),
        ]
    )
    def test_recurring_schedule_operation_validation(self, _name, operation, value, interval, expected_status):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="recurring-op-flag", name="Recurring Op Flag"
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": operation, "value": value},
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                "recurrence_interval": interval,
            },
        )

        response_data = response.json()
        assert response.status_code == expected_status, response_data

        if expected_status == status.HTTP_201_CREATED:
            assert response_data["is_recurring"] is True
            assert response_data["recurrence_interval"] == interval
        else:
            assert "not supported for add_release_condition" in str(response_data)

    def test_non_recurring_schedule_rejects_interval(self):
        """Test that new non-recurring schedules cannot have recurrence_interval set"""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="non-recurring-flag", name="Non Recurring Flag"
        )

        payload = {"operation": "update_status", "value": True}

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": payload,
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": False,
                "recurrence_interval": "daily",  # Should be rejected
            },
        )

        response_data = response.json()

        # Creating with is_recurring=False and recurrence_interval set is not allowed
        # This prevents accidentally creating "paused" recurring schedules
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "recurrence_interval" in response_data.get("attr", "")

    def test_recurring_schedule_appears_in_list(self):
        """Test that recurring schedules are returned with correct fields in list endpoint"""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="list-recurring-flag", name="List Recurring Flag"
        )

        ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at="2024-01-15T09:00:00Z",
            is_recurring=True,
            recurrence_interval="monthly",
            created_by=self.user,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={"model_name": "FeatureFlag", "record_id": str(feature_flag.id)},
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["count"] == 1
        result = response_data["results"][0]
        assert result["is_recurring"] is True
        assert result["recurrence_interval"] == "monthly"

    def test_cannot_update_record_id(self):
        """Updating record_id is rejected to prevent cross-tenant manipulation."""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="immutable-target-flag", name="Immutable Target Flag"
        )
        other_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="other-flag", name="Other Flag"
        )

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at="2024-01-15T09:00:00Z",
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/scheduled_changes/{scheduled_change.id}/",
            data={"record_id": str(other_flag.id)},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "Cannot change the target record" in str(response.json())

        scheduled_change.refresh_from_db()
        assert str(scheduled_change.record_id) == str(feature_flag.id)

    def test_cannot_update_model_name_to_invalid_value(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="immutable-model-flag", name="Immutable Model Flag"
        )

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at="2024-01-15T09:00:00Z",
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/scheduled_changes/{scheduled_change.id}/",
            data={"model_name": "SomeOtherModel"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "model_name" in str(response.json())

        scheduled_change.refresh_from_db()
        assert scheduled_change.model_name == "FeatureFlag"

    def test_validate_rejects_model_name_change_on_update(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="validate-model-flag", name="Validate Model Flag"
        )

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at="2024-01-15T09:00:00Z",
            created_by=self.user,
        )

        serializer = ScheduledChangeSerializer(instance=scheduled_change)
        with self.assertRaises(serializers.ValidationError) as ctx:
            serializer.validate({"model_name": "SomeFutureModel"})
        assert "Cannot change the model type" in str(ctx.exception)

    def test_cannot_update_record_id_via_put(self):
        feature_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="put-flag", name="Put Flag")
        other_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="other-put-flag", name="Other Put Flag"
        )

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at="2024-01-15T09:00:00Z",
            created_by=self.user,
        )

        response = self.client.put(
            f"/api/projects/{self.team.id}/scheduled_changes/{scheduled_change.id}/",
            data={
                "record_id": str(other_flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": False},
                "scheduled_at": "2024-01-15T09:00:00Z",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "Cannot change the target record" in str(response.json())

        scheduled_change.refresh_from_db()
        assert str(scheduled_change.record_id) == str(feature_flag.id)

    def test_can_create_recurring_schedule_with_cron_expression(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="cron-flag", name="Cron Flag"
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": True},
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                "cron_expression": "0 9 * * 1-5",
            },
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["is_recurring"] is True
        assert response_data["cron_expression"] == "0 9 * * 1-5"
        assert response_data["recurrence_interval"] is None

    def test_rejects_both_cron_and_interval(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="both-flag", name="Both Flag"
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": True},
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                "cron_expression": "0 9 * * 1-5",
                "recurrence_interval": "daily",
            },
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "Cannot set both" in str(response_data)

    @parameterized.expand(
        [
            ("wrong_field_count", "not a cron", "5-field"),
            ("six_fields_rejected", "* * * * * *", "5-field"),
            ("invalid_syntax", "99 99 99 99 99", "Invalid cron expression"),
        ]
    )
    def test_rejects_invalid_cron_expression(self, _name, expr, expected_fragment):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="invalid-cron-flag", name="Invalid Cron Flag"
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": True},
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                "cron_expression": expr,
            },
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert expected_fragment in str(response_data)

    def test_non_recurring_rejects_cron_on_create(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="cron-non-recurring-flag", name="Cron Non-recurring Flag"
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": True},
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": False,
                "cron_expression": "0 9 * * 1-5",
            },
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "cron_expression" in str(response_data)

    def test_cron_recurring_blocks_add_release_condition(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="cron-arc-flag", name="Cron ARC Flag"
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": {
                    "operation": "add_release_condition",
                    "value": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                },
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                "cron_expression": "0 9 * * 1-5",
            },
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "not supported for add_release_condition" in str(response_data)

    def test_can_update_other_fields_without_changing_record_id(self):
        """Non-target fields like payload and scheduled_at can still be updated."""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="updatable-flag", name="Updatable Flag"
        )

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at="2024-01-15T09:00:00Z",
            created_by=self.user,
        )

        with patch(
            "products.feature_flags.backend.api.scheduled_change.CanEditFeatureFlag.has_object_permission",
            return_value=True,
        ):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/scheduled_changes/{scheduled_change.id}/",
                data={"payload": {"operation": "update_status", "value": True}},
            )

        assert response.status_code == status.HTTP_200_OK, response.json()

        scheduled_change.refresh_from_db()
        assert scheduled_change.payload == {"operation": "update_status", "value": True}

    @parameterized.expand(
        [
            ("denied_without_permission", False, status.HTTP_400_BAD_REQUEST, "You don't have edit permissions", False),
            ("allowed_with_permission", True, status.HTTP_200_OK, None, True),
        ]
    )
    def test_patch_respects_feature_flag_edit_permission(
        self, _name, has_permission, expected_status, expected_error_fragment, payload_should_change
    ):
        """PATCH must enforce CanEditFeatureFlag, matching the create-time check."""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key=f"perm-flag-{_name}", name="Perm Flag"
        )

        original_payload = {"operation": "update_status", "value": False}
        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload=original_payload,
            scheduled_at="2024-01-15T09:00:00Z",
            created_by=self.user,
        )

        new_payload = {"operation": "update_status", "value": True}
        with patch(
            "products.feature_flags.backend.api.scheduled_change.CanEditFeatureFlag.has_object_permission",
            return_value=has_permission,
        ):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/scheduled_changes/{scheduled_change.id}/",
                data={"payload": new_payload},
            )

        assert response.status_code == expected_status, response.json()
        if expected_error_fragment:
            assert expected_error_fragment in str(response.json())

        scheduled_change.refresh_from_db()
        assert scheduled_change.payload == (new_payload if payload_should_change else original_payload)

    @parameterized.expand(
        [
            ("reset_executed_at", {"executed_at": None}),
            ("replace_payload", {"payload": {"operation": "update_status", "value": True}}),
            ("reschedule", {"scheduled_at": "2030-01-15T09:00:00Z"}),
        ]
    )
    def test_completed_one_time_scheduled_change_is_immutable(self, _name, patch_body):
        """A one-time schedule that already executed cannot be mutated — blocks replay + privilege escalation."""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key=f"immutable-{_name}", name="Immutable Flag"
        )

        original_executed_at = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        original_payload = {"operation": "update_status", "value": False}
        original_scheduled_at = datetime(2024, 1, 15, 9, 0, 0, tzinfo=UTC)
        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload=original_payload,
            scheduled_at=original_scheduled_at,
            executed_at=original_executed_at,
            created_by=self.user,
        )

        with patch(
            "products.feature_flags.backend.api.scheduled_change.CanEditFeatureFlag.has_object_permission",
            return_value=True,
        ):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/scheduled_changes/{scheduled_change.id}/",
                data=patch_body,
            )

        # validate() rejects all mutations of a completed one-time schedule.
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "already executed" in str(response.json())

        scheduled_change.refresh_from_db()
        assert scheduled_change.executed_at == original_executed_at, (
            f"executed_at changed to {scheduled_change.executed_at} (status={response.status_code})"
        )
        assert scheduled_change.payload == original_payload, (
            f"payload changed to {scheduled_change.payload} (status={response.status_code})"
        )
        assert scheduled_change.scheduled_at == original_scheduled_at, (
            f"scheduled_at changed to {scheduled_change.scheduled_at} (status={response.status_code})"
        )


class TestScheduledChangePersonalAPIKeyAccess(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="pak-flag", name="PAK Flag"
        )
        self.scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=str(self.feature_flag.id),
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at=datetime(2023, 12, 8, 12, 0, 0, tzinfo=UTC),
            created_by=self.user,
        )

    def _authenticate_with_scopes(self, scopes: list[str]) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

    def _write_request(self, action: str):
        base = f"/api/projects/{self.team.id}/scheduled_changes/"
        if action == "create":
            return self.client.post(
                base,
                data={
                    "record_id": str(self.feature_flag.id),
                    "model_name": "FeatureFlag",
                    "payload": {"operation": "update_status", "value": True},
                    "scheduled_at": "2023-12-09T12:00:00Z",
                },
            )
        if action == "update":
            return self.client.patch(
                f"{base}{self.scheduled_change.id}/",
                data={"payload": {"operation": "update_status", "value": True}, "scheduled_at": "2023-12-09T12:00:00Z"},
            )
        if action == "delete":
            return self.client.delete(f"{base}{self.scheduled_change.id}/")
        raise ValueError(f"unknown action: {action}")

    @parameterized.expand(["list", "retrieve"])
    def test_read_succeeds_with_read_scope(self, action: str) -> None:
        self._authenticate_with_scopes(["feature_flag:read"])

        if action == "list":
            response = self.client.get(f"/api/projects/{self.team.id}/scheduled_changes/")
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert self.scheduled_change.id in [row["id"] for row in response.json()["results"]]
        else:
            response = self.client.get(f"/api/projects/{self.team.id}/scheduled_changes/{self.scheduled_change.id}/")
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert response.json()["id"] == self.scheduled_change.id

    @parameterized.expand(["list", "retrieve"])
    def test_read_forbidden_with_unrelated_scope(self, action: str) -> None:
        self._authenticate_with_scopes(["dashboard:read"])

        if action == "list":
            url = f"/api/projects/{self.team.id}/scheduled_changes/"
        else:
            url = f"/api/projects/{self.team.id}/scheduled_changes/{self.scheduled_change.id}/"

        response = self.client.get(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    @parameterized.expand(
        [
            ("create", status.HTTP_201_CREATED),
            ("update", status.HTTP_200_OK),
            ("delete", status.HTTP_204_NO_CONTENT),
        ]
    )
    def test_write_succeeds_with_write_scope(self, action: str, expected_status: int) -> None:
        # The key belongs to self.user, who created the flag with no access controls, so the real
        # per-flag CanEditFeatureFlag check passes — exercise it rather than mocking it out.
        self._authenticate_with_scopes(["feature_flag:write"])

        response = self._write_request(action)

        assert response.status_code == expected_status, response.content

    @parameterized.expand(["create", "update", "delete"])
    def test_write_forbidden_with_read_only_scope(self, action: str) -> None:
        self._authenticate_with_scopes(["feature_flag:read"])

        response = self._write_request(action)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        # The forbidden write must not have taken effect.
        if action == "create":
            assert ScheduledChange.objects.filter(team=self.team).count() == 1
        elif action == "update":
            self.scheduled_change.refresh_from_db()
            assert self.scheduled_change.payload == {"operation": "update_status", "value": False}
        else:
            assert ScheduledChange.objects.filter(id=self.scheduled_change.id).exists()

    def test_read_scope_is_team_scoped(self):
        # A schedule under a different team in the same org must not leak through the
        # team-scoped endpoint, even for a key whose user can access both teams.
        other_team = create_team(organization=self.organization)
        other_change = ScheduledChange.objects.create(
            team=other_team,
            record_id="999",
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at=datetime(2023, 12, 8, 12, 0, 0, tzinfo=UTC),
            created_by=self.user,
        )

        self._authenticate_with_scopes(["feature_flag:read"])

        list_response = self.client.get(f"/api/projects/{self.team.id}/scheduled_changes/")
        assert list_response.status_code == status.HTTP_200_OK, list_response.json()
        ids = [row["id"] for row in list_response.json()["results"]]
        assert other_change.id not in ids

        retrieve_response = self.client.get(f"/api/projects/{self.team.id}/scheduled_changes/{other_change.id}/")
        assert retrieve_response.status_code == status.HTTP_404_NOT_FOUND, retrieve_response.json()


class TestScheduledChangeAccessControl(BaseAccessControlTest):
    """Scheduled changes inherit the feature_flag resource, so feature-flag access controls gate reads."""

    def setUp(self):
        super().setUp()
        self.feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="ac-flag", name="AC Flag"
        )
        self.scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=str(self.feature_flag.id),
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at=datetime(2023, 12, 8, 12, 0, 0, tzinfo=UTC),
            created_by=self.user,
        )

    def test_member_with_default_access_can_read(self):
        self._org_membership(OrganizationMembership.Level.MEMBER)

        response = self.client.get(f"/api/projects/{self.team.id}/scheduled_changes/")

        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_member_blocked_when_feature_flag_resource_denied(self):
        # An admin removes feature_flag access org-wide; scheduled changes follow the same resource.
        self._org_membership(OrganizationMembership.Level.ADMIN)
        assert (
            self._put_global_access_control({"resource": "feature_flag", "access_level": "none"}).status_code
            == status.HTTP_200_OK
        )
        self._org_membership(OrganizationMembership.Level.MEMBER)

        list_response = self.client.get(f"/api/projects/{self.team.id}/scheduled_changes/")
        assert list_response.status_code == status.HTTP_403_FORBIDDEN, list_response.json()

        retrieve_response = self.client.get(
            f"/api/projects/{self.team.id}/scheduled_changes/{self.scheduled_change.id}/"
        )
        assert retrieve_response.status_code == status.HTTP_403_FORBIDDEN, retrieve_response.json()

    def _make_schedule_for_flag(self, key: str) -> tuple[FeatureFlag, ScheduledChange]:
        # Owned by another user so the requesting user isn't the flag creator (creators bypass
        # object-level access controls).
        flag_owner = User.objects.create_and_join(self.organization, f"{key}-owner@example.com", "password123")
        flag = FeatureFlag.objects.create(team=self.team, created_by=flag_owner, key=key, name=key)
        change = ScheduledChange.objects.create(
            team=self.team,
            record_id=str(flag.id),
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at=datetime(2023, 12, 8, 12, 0, 0, tzinfo=UTC),
            created_by=self.user,
        )
        return flag, change

    def _set_flag_access(self, flag: FeatureFlag, access_level: str) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="feature_flag",
            resource_id=str(flag.id),
            access_level=access_level,
            organization_member=self.organization_membership,
        )

    def test_per_flag_denial_hides_schedule_from_reads(self):
        # The target flag lives in record_id, so per-flag access must be enforced on reads.
        _, denied_change = self._make_schedule_for_flag("denied-flag")
        self._set_flag_access(FeatureFlag.objects.get(id=denied_change.record_id), "none")
        self._org_membership(OrganizationMembership.Level.MEMBER)

        list_response = self.client.get(f"/api/projects/{self.team.id}/scheduled_changes/")
        assert list_response.status_code == status.HTTP_200_OK, list_response.json()
        ids = [row["id"] for row in list_response.json()["results"]]
        assert denied_change.id not in ids
        # A schedule for an accessible flag is still returned.
        assert self.scheduled_change.id in ids

        retrieve_response = self.client.get(f"/api/projects/{self.team.id}/scheduled_changes/{denied_change.id}/")
        assert retrieve_response.status_code == status.HTTP_404_NOT_FOUND, retrieve_response.json()

    def test_per_flag_denial_blocks_delete(self):
        _, denied_change = self._make_schedule_for_flag("denied-delete-flag")
        self._set_flag_access(FeatureFlag.objects.get(id=denied_change.record_id), "none")
        self._org_membership(OrganizationMembership.Level.MEMBER)

        response = self.client.delete(f"/api/projects/{self.team.id}/scheduled_changes/{denied_change.id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert ScheduledChange.objects.filter(id=denied_change.id).exists()

    def test_viewer_only_member_can_read_but_not_delete_schedule(self):
        flag, viewer_change = self._make_schedule_for_flag("viewer-flag")
        self._set_flag_access(flag, "viewer")
        self._org_membership(OrganizationMembership.Level.MEMBER)

        retrieve_response = self.client.get(f"/api/projects/{self.team.id}/scheduled_changes/{viewer_change.id}/")
        assert retrieve_response.status_code == status.HTTP_200_OK, retrieve_response.json()

        delete_response = self.client.delete(f"/api/projects/{self.team.id}/scheduled_changes/{viewer_change.id}/")
        assert delete_response.status_code == status.HTTP_403_FORBIDDEN, delete_response.content
        assert ScheduledChange.objects.filter(id=viewer_change.id).exists()

    def test_delete_orphaned_schedule_when_flag_deleted(self):
        # The target flag has been hard-deleted, so the edit check can't resolve it; the orphaned
        # schedule must still be deletable for team-scoped cleanup.
        _, orphaned_change = self._make_schedule_for_flag("orphan-flag")
        FeatureFlag.objects.filter(id=orphaned_change.record_id).delete()
        self._org_membership(OrganizationMembership.Level.MEMBER)

        response = self.client.delete(f"/api/projects/{self.team.id}/scheduled_changes/{orphaned_change.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
        assert not ScheduledChange.objects.filter(id=orphaned_change.id).exists()

    def test_delete_schedule_with_non_numeric_record_id(self):
        # The edit check's int cast raises ValueError for a non-numeric record_id; like the deleted-flag
        # case it has no flag-level permission to enforce, so the schedule must still be deletable.
        change = ScheduledChange.objects.create(
            team=self.team,
            record_id="not-a-number",
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at=datetime(2023, 12, 8, 12, 0, 0, tzinfo=UTC),
            created_by=self.user,
        )
        self._org_membership(OrganizationMembership.Level.MEMBER)

        response = self.client.delete(f"/api/projects/{self.team.id}/scheduled_changes/{change.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
        assert not ScheduledChange.objects.filter(id=change.id).exists()

    def test_create_requires_resource_write_despite_object_editor_grant(self):
        # Create is gated at the resource level: AccessControlPermission denies `create` before the
        # per-object fallback that read/update/delete fall through to. So a member whose feature_flag
        # resource access is below editor cannot schedule a new change even with an object-level editor
        # grant on the flag — stricter than editing the flag directly. Pinned here so it can't regress
        # silently; the serializer's per-flag check never runs because the 403 fires first.
        flag_owner = User.objects.create_and_join(self.organization, "obj-grant-owner@example.com", "password123")
        flag = FeatureFlag.objects.create(team=self.team, created_by=flag_owner, key="object-grant-flag", name="OG")

        self._org_membership(OrganizationMembership.Level.ADMIN)
        assert (
            self._put_global_access_control({"resource": "feature_flag", "access_level": "viewer"}).status_code
            == status.HTTP_200_OK
        )
        self._set_flag_access(flag, "editor")
        self._org_membership(OrganizationMembership.Level.MEMBER)

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": True},
                "scheduled_at": "2023-12-09T12:00:00Z",
            },
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert not ScheduledChange.objects.filter(record_id=str(flag.id)).exists()
