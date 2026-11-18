from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import ActivityLog

from products.approvals.backend.models import ApprovalPolicy, ChangeRequest
from products.approvals.backend.services import ChangeRequestService
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _rollout(percentage: int) -> dict[str, Any]:
    return {"filters": {"groups": [{"properties": [], "rollout_percentage": percentage}]}}


class TestFeatureFlagRollbackReason(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="checkout", filters=_rollout(50)["filters"]
        )

    def _patch(self, body: dict[str, Any]) -> Any:
        return self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{self.flag.pk}", body, format="json")

    @parameterized.expand(
        [
            ("lower_rollout", _rollout(10), True, status.HTTP_409_CONFLICT),
            ("disable", {"active": False}, True, status.HTTP_409_CONFLICT),
            ("delete", {"deleted": True}, True, status.HTTP_409_CONFLICT),
            ("higher_rollout", _rollout(80), True, status.HTTP_200_OK),
            ("lower_rollout_sent_again_without_asking", _rollout(10), False, status.HTTP_200_OK),
            (
                "note_without_reason",
                {**_rollout(10), "rollback_reason_note": "Checkout 500s"},
                False,
                status.HTTP_400_BAD_REQUEST,
            ),
            ("unknown_reason", {**_rollout(10), "rollback_reason": "bogus"}, False, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_asks_for_a_reason_only_when_the_edit_lowers_exposure(
        self, _name: str, edit: dict[str, Any], ask: bool, expected_status: int
    ) -> None:
        version = self.flag.version or 0

        response = self._patch({**edit, "ask_rollback_reason": ask})

        assert response.status_code == expected_status
        self.flag.refresh_from_db()
        if expected_status == status.HTTP_409_CONFLICT:
            assert response.json()["code"] == "rollback_reason_required"
        assert self.flag.version == (version + 1 if expected_status == status.HTTP_200_OK else version)

    def test_asks_for_a_reason_when_the_stored_condition_has_no_properties_key(self) -> None:
        FeatureFlag.objects.filter(pk=self.flag.pk).update(filters={"groups": [{"rollout_percentage": 50}]})

        response = self._patch({**_rollout(10), "ask_rollback_reason": True})

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["code"] == "rollback_reason_required"

    @patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
    def test_an_edit_that_needs_approval_applies_without_asking_for_a_reason(self, _mock_enabled: MagicMock) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}
        ]
        self.organization.save()
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.disable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

        response = self._patch({"active": False, "ask_rollback_reason": True})

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["code"] == "approval_required"
        change_request = ChangeRequest.objects.get(team=self.team)
        assert ChangeRequestService(change_request, self.user).approve().status == "applied"
        self.flag.refresh_from_db()
        assert self.flag.active is False

    @parameterized.expand([("lowering_edit", 10, "lowers"), ("raising_edit", 80, "raises")])
    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_stores_the_reason_on_the_activity_log_entry_of_the_edit(
        self, _name: str, rollout: int, direction: str, mock_report_user_action: MagicMock
    ) -> None:
        response = self._patch(
            {**_rollout(rollout), "rollback_reason": "errors", "rollback_reason_note": "Checkout 500s"}
        )

        assert response.status_code == status.HTTP_200_OK
        entry = ActivityLog.objects.filter(scope="FeatureFlag", item_id=str(self.flag.pk)).latest("created_at")
        assert entry.detail is not None
        assert entry.detail["context"] == {
            "rollback_reason": "errors",
            "rollback_reason_note": "Checkout 500s",
            "exposure_direction": direction,
        }
        (properties,) = [
            call.args[2]
            for call in mock_report_user_action.call_args_list
            if call.args[1] == "feature flag rollback reason given"
        ]
        assert properties == {
            "feature_flag_id": self.flag.pk,
            "feature_flag_version": (self.flag.version or 0) + 1,
            "rollback_reason": "errors",
            "has_note": True,
            "exposure_direction": direction,
        }
