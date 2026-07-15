from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework.exceptions import ValidationError

from posthog.constants import AvailableFeature

from products.approvals.backend.exceptions import ApprovalRequired
from products.approvals.backend.models import ApprovalPolicy
from products.feature_flags.backend.facade.api import (
    _roll_out_variant,
    archive_flag,
    flag_disable_requires_approval,
    ship_variant,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestFeatureFlagFacadeGatedWrites(APIBaseTest):
    def _create_flag(self, *, active: bool = True, filters: dict | None = None) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="facade-gated-flag",
            active=active,
            filters=filters if filters is not None else {"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

    def test_archive_active_flag_with_disable_succeeds(self):
        flag = self._create_flag(active=True)

        archive_flag(flag, team=self.team, user=self.user, disable_if_active=True)

        flag.refresh_from_db()
        assert flag.archived is True
        assert flag.active is False

    def test_flag_disable_requires_approval_reflects_policy(self):
        assert flag_disable_requires_approval(self.team) is False

        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.disable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )
        assert flag_disable_requires_approval(self.team) is True

    def test_archive_active_flag_without_disable_is_rejected(self):
        flag = self._create_flag(active=True)

        with self.assertRaises(ValidationError):
            archive_flag(flag, team=self.team, user=self.user)

        flag.refresh_from_db()
        assert flag.archived is False
        assert flag.active is True

    def test_ship_variant_without_base_filters_uses_flag_filters(self):
        flag = self._create_flag(
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            }
        )

        ship_variant(flag, "test", team=self.team, user=self.user)

        flag.refresh_from_db()
        variants = flag.filters["multivariate"]["variants"]
        assert {v["key"]: v["rollout_percentage"] for v in variants} == {"control": 0, "test": 100}
        # Default mode: no catch-all prepended, the existing release condition is preserved
        assert len(flag.filters["groups"]) == 1
        assert flag.filters["groups"][0]["rollout_percentage"] == 100

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


class TestRollOutVariant:
    def test_transform_filters_default_preserves_groups(self):
        current_filters = {
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "payloads": {},
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                    {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                ]
            },
            "aggregation_group_type_index": None,
        }

        result = _roll_out_variant(current_filters, "test")

        # Variant distribution flipped
        assert result["multivariate"]["variants"] == [
            {"key": "control", "name": "Control Group", "rollout_percentage": 0},
            {"key": "test", "name": "Test Variant", "rollout_percentage": 100},
        ]
        # Groups preserved exactly — no catch-all prepended in default mode
        assert result["groups"] == current_filters["groups"]
        assert result["payloads"] == {}
        assert result["aggregation_group_type_index"] is None

    def test_transform_filters_release_to_everyone_prepends_catch_all(self):
        current_filters = {
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "payloads": {},
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                    {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                ]
            },
            "aggregation_group_type_index": None,
        }

        result = _roll_out_variant(
            current_filters,
            "test",
            release_to_everyone=True,
            release_condition_description="Rolled out by the caller.",
        )

        assert result["multivariate"]["variants"] == [
            {"key": "control", "name": "Control Group", "rollout_percentage": 0},
            {"key": "test", "name": "Test Variant", "rollout_percentage": 100},
        ]
        assert result["groups"][0] == {
            "properties": [],
            "rollout_percentage": 100,
            "description": "Rolled out by the caller.",
        }
        assert result["groups"][1:] == [{"properties": [], "rollout_percentage": 100}]
        assert result["payloads"] == {}
        assert result["aggregation_group_type_index"] is None

    def test_transform_filters_default_does_not_mutate_input(self):
        """Defensive: ensure the function returns a new groups list without mutating caller's filters."""
        original_groups = [{"properties": [], "rollout_percentage": 50}]
        current_filters = {
            "groups": original_groups,
            "multivariate": {
                "variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ]
            },
        }

        result = _roll_out_variant(current_filters, "test")

        # Caller's list reference is untouched
        assert current_filters["groups"] is original_groups
        # Result's groups equals original by value but is a distinct list object
        assert result["groups"] == original_groups
        assert result["groups"] is not original_groups

    def test_transform_filters_multiple_variants_with_payloads(self):
        current_filters = {
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "payloads": {
                "test_1": "{key: 'test_1'}",
                "test_2": "{key: 'test_2'}",
                "test_3": "{key: 'test_3'}",
                "control": "{key: 'control'}",
            },
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "This is control", "rollout_percentage": 25},
                    {"key": "test_1", "name": "This is test_1", "rollout_percentage": 25},
                    {"key": "test_2", "name": "This is test_2", "rollout_percentage": 25},
                    {"key": "test_3", "name": "This is test_3", "rollout_percentage": 25},
                ]
            },
            "aggregation_group_type_index": 1,
        }

        result = _roll_out_variant(current_filters, "control", release_to_everyone=True)

        assert result["multivariate"]["variants"] == [
            {"key": "control", "name": "This is control", "rollout_percentage": 100},
            {"key": "test_1", "name": "This is test_1", "rollout_percentage": 0},
            {"key": "test_2", "name": "This is test_2", "rollout_percentage": 0},
            {"key": "test_3", "name": "This is test_3", "rollout_percentage": 0},
        ]
        # No description on the catch-all when the caller doesn't pass one
        assert result["groups"][0] == {"properties": [], "rollout_percentage": 100}
        assert result["groups"][1:] == [{"properties": [], "rollout_percentage": 100}]
        assert result["payloads"] == current_filters["payloads"]
        assert result["aggregation_group_type_index"] == 1
