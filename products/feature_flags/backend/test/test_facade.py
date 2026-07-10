from copy import deepcopy

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
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
from products.feature_flags.backend.facade.filters import (
    group_cohort_restriction_blocker,
    groups_carry_restriction_marker,
    restrict_groups_to_cohort,
    strip_group_cohort_restriction,
)
from products.feature_flags.backend.facade.rules import ExperimentRuleConfig, HoldoutRef, experiment_rule_from_filters
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


MARKER_KWARGS = {"marker_key": "restricted", "cohort_key": "restricted_cohort", "marker_note": "Restricted."}


class TestFilterTransforms:
    def test_restrict_then_strip_round_trips(self):
        original = {
            "groups": [
                {"properties": [{"key": "email", "type": "person", "value": "@posthog.com"}], "rollout_percentage": 50},
                {"properties": [], "rollout_percentage": 100, "description": "User prose"},
            ],
            "multivariate": {"variants": [{"key": "control", "rollout_percentage": 100}]},
        }
        pristine = deepcopy(original)

        restricted = restrict_groups_to_cohort(original, 42, **MARKER_KWARGS)

        assert all(group["restricted"] is True for group in restricted["groups"])
        assert all(group["restricted_cohort"] == 42 for group in restricted["groups"])
        assert all(group["properties"][-1]["value"] == 42 for group in restricted["groups"])
        assert restricted["groups"][0]["description"] == "Restricted."
        assert restricted["groups"][1]["description"] == "Restricted. User prose"
        assert original == pristine

        stripped, cohort_ids = strip_group_cohort_restriction(restricted, **MARKER_KWARGS)

        # Exact round-trip, including restored absence of the added description key —
        # and the shared cohort id reported once, not per group.
        assert stripped == pristine
        assert cohort_ids == [42]

    def test_strip_leaves_unstamped_groups_and_user_cohort_conditions_untouched(self):
        user_cohort = {"key": "id", "type": "cohort", "value": 7, "operator": "in"}
        filters = {
            "groups": [
                {
                    "properties": [user_cohort, {"key": "id", "type": "cohort", "value": 42, "operator": "in"}],
                    "restricted": True,
                    "restricted_cohort": 42,
                    "description": "Restricted.",
                },
                {"properties": [user_cohort], "rollout_percentage": 100},
            ]
        }

        stripped, cohort_ids = strip_group_cohort_restriction(filters, **MARKER_KWARGS)

        assert cohort_ids == [42]
        assert stripped["groups"][0] == {"properties": [user_cohort]}
        assert stripped["groups"][1] == filters["groups"][1]

    @parameterized.expand(
        [
            ("all_stamped", [{"restricted": True}, {"restricted": True}], True),
            ("one_unstamped", [{"restricted": True}, {}], False),
            ("empty_groups", [], False),
        ]
    )
    def test_groups_carry_restriction_marker(self, _name: str, groups: list[dict], expected: bool):
        assert groups_carry_restriction_marker({"groups": groups}, marker_key="restricted") is expected

    @parameterized.expand(
        [
            ("group_aggregation_wins", {"aggregation_group_type_index": 1, "holdout": {"id": 1}}, "group_aggregation"),
            ("holdout", {"holdout_groups": [{}], "groups": [{}]}, "holdout"),
            ("super_groups", {"super_groups": [{}], "groups": [{}]}, "super_groups"),
            ("no_groups", {"groups": []}, "no_groups"),
            ("plain_groups_ok", {"groups": [{"properties": []}]}, None),
        ]
    )
    def test_group_cohort_restriction_blocker(self, _name: str, filters: dict, expected: str | None):
        assert group_cohort_restriction_blocker(filters) == expected


class TestExperimentRuleFromFilters:
    @parameterized.expand(
        [
            (
                "full_v1_filters",
                {
                    "groups": [
                        {"properties": [], "rollout_percentage": 40},
                        {"properties": [], "rollout_percentage": 100},
                    ],
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 50},
                            {"key": "test", "rollout_percentage": 50},
                        ]
                    },
                    "aggregation_group_type_index": 2,
                    "holdout": {"id": 7, "exclusion_percentage": 10},
                },
                ExperimentRuleConfig(
                    variants=[
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ],
                    rollout_percentage=40,
                    assign_variant_by=2,
                    holdout=HoldoutRef(id=7, exclusion_percentage=10),
                ),
            ),
            (
                "empty_filters",
                {},
                ExperimentRuleConfig(variants=[], rollout_percentage=None, assign_variant_by=None, holdout=None),
            ),
            (
                "group_without_rollout_and_null_holdout",
                {"groups": [{"properties": []}], "holdout": None, "multivariate": {"variants": []}},
                ExperimentRuleConfig(variants=[], rollout_percentage=None, assign_variant_by=None, holdout=None),
            ),
        ]
    )
    def test_derivation(self, _name, filters, expected):
        assert experiment_rule_from_filters(filters) == expected
