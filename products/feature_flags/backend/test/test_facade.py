from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework.exceptions import ValidationError

from posthog.constants import AvailableFeature

from products.approvals.backend.exceptions import ApprovalRequired
from products.approvals.backend.models import ApprovalPolicy
from products.feature_flags.backend.facade.api import archive_flag
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestFeatureFlagFacadeGatedWrites(APIBaseTest):
    def _create_flag(self, *, active: bool = True) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="facade-gated-flag",
            active=active,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

    def test_archive_active_flag_without_disable_is_rejected(self):
        flag = self._create_flag(active=True)

        with self.assertRaises(ValidationError):
            archive_flag(flag, team=self.team, user=self.user)

        flag.refresh_from_db()
        assert flag.archived is False
        assert flag.active is True

    @patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
    def test_archive_with_disable_honors_disable_approval_policy(self, _mock_enabled):
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
        flag = self._create_flag(active=True)

        with self.assertRaises(ApprovalRequired):
            archive_flag(flag, team=self.team, user=self.user, disable_if_active=True)

        flag.refresh_from_db()
        assert flag.archived is False
        assert flag.active is True
