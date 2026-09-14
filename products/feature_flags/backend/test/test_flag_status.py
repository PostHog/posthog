from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from products.feature_flags.backend.flag_status import (
    FeatureFlagStatus,
    FeatureFlagStatusChecker,
    filter_flags_by_active_param,
    filter_stale_flags,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestFilterFlagsByActiveParam(BaseTest):
    def setUp(self):
        super().setUp()
        self.enabled = FeatureFlag.objects.create(team=self.team, key="enabled", active=True, created_by=self.user)
        self.disabled = FeatureFlag.objects.create(team=self.team, key="disabled", active=False, created_by=self.user)
        # Config-based stale: 30+ days old, no usage data, fully rolled out to 100%
        self.stale = FeatureFlag.objects.create(
            team=self.team,
            key="stale",
            active=True,
            created_at=timezone.now() - timedelta(days=60),
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )
        # Usage-based stale: active but not evaluated in 30+ days
        self.stale_by_usage = FeatureFlag.objects.create(
            team=self.team,
            key="stale-by-usage",
            active=True,
            last_called_at=timezone.now() - timedelta(days=35),
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            created_by=self.user,
        )
        # Multivariate stale: one variant at 100% plus a fully rolled out release condition
        self.stale_multivariate = FeatureFlag.objects.create(
            team=self.team,
            key="stale-multivariate",
            active=True,
            created_at=timezone.now() - timedelta(days=60),
            filters={
                "multivariate": {"variants": [{"key": "control", "rollout_percentage": 100}]},
                "groups": [{"properties": [], "rollout_percentage": 100}],
            },
            created_by=self.user,
        )
        # Empty-variants stale: a present-but-empty multivariate block routes through the boolean
        # branch (both the SQL filter's jsonb_array_length(variants)=0 and the checker's has_variants).
        self.stale_empty_variants = FeatureFlag.objects.create(
            team=self.team,
            key="stale-empty-variants",
            active=True,
            created_at=timezone.now() - timedelta(days=60),
            filters={
                "multivariate": {"variants": []},
                "groups": [{"properties": [], "rollout_percentage": 100}],
            },
            created_by=self.user,
        )

    def _filter(self, value):
        return set(
            filter_flags_by_active_param(FeatureFlag.objects.filter(team=self.team), value).values_list(
                "key", flat=True
            )
        )

    def test_filters_enabled(self):
        assert self._filter("true") == {
            "enabled",
            "stale",
            "stale-by-usage",
            "stale-multivariate",
            "stale-empty-variants",
        }

    def test_filters_disabled(self):
        assert self._filter("false") == {"disabled"}

    def test_filters_stale(self):
        assert self._filter("STALE") == {"stale", "stale-by-usage", "stale-multivariate", "stale-empty-variants"}

    def test_active_param_is_case_insensitive(self):
        assert self._filter("True") == self._filter("true")
        assert self._filter("False") == self._filter("false")

    def test_accepts_native_booleans(self):
        assert self._filter(True) == {
            "enabled",
            "stale",
            "stale-by-usage",
            "stale-multivariate",
            "stale-empty-variants",
        }
        assert self._filter(False) == {"disabled"}

    def _checker_stale(self) -> set[str]:
        return {
            flag.key
            for flag in FeatureFlag.objects.filter(team=self.team)
            if FeatureFlagStatusChecker(feature_flag=flag).get_status()[0] == FeatureFlagStatus.STALE
        }

    # (flag key, extra FeatureFlag kwargs, whether that flag is stale). Each case creates its
    # flag, then asserts the filter and the checker agree across the whole team, so setUp's four
    # stale flags are re-checked on every case. Most cases add a shape that must not be stale,
    # because setUp already covers the stale ones.
    @parameterized.expand(
        [
            (
                "recently_evaluated",
                {
                    "created_at": timezone.now() - timedelta(days=60),
                    "last_called_at": timezone.now() - timedelta(days=1),
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                },
                False,
            ),
            (
                "boolean_zero_rollout",
                {
                    "created_at": timezone.now() - timedelta(days=60),
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 0}]},
                },
                False,
            ),
            (
                "partial_rollout",
                {
                    "created_at": timezone.now() - timedelta(days=60),
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
                },
                False,
            ),
            (
                "targeted_condition_at_full_rollout",
                {
                    "created_at": timezone.now() - timedelta(days=60),
                    "filters": {
                        "groups": [{"properties": [{"key": "email", "value": "x"}], "rollout_percentage": 100}]
                    },
                },
                False,
            ),
            (
                "multivariate_split_variants",
                {
                    "created_at": timezone.now() - timedelta(days=60),
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 50},
                                {"key": "test", "rollout_percentage": 50},
                            ]
                        },
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                    },
                },
                False,
            ),
            (
                "young_flag_at_full_rollout",
                {
                    "created_at": timezone.now() - timedelta(days=5),
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                },
                False,
            ),
            (
                "disabled_flag_at_full_rollout",
                {
                    "active": False,
                    "created_at": timezone.now() - timedelta(days=60),
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                },
                False,
            ),
            # Only case that reaches the usage branch's `active=True` guard, because every
            # other disabled case leaves `last_called_at` NULL and stops at the config branch.
            (
                "disabled_flag_with_old_last_called_at",
                {
                    "active": False,
                    "last_called_at": timezone.now() - timedelta(days=35),
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
                },
                False,
            ),
            # Only case that reaches the config branch's last OR arm, where `filters` being
            # non-nullable makes `= '{}'` the whole test.
            (
                "empty_filters_object",
                {
                    "created_at": timezone.now() - timedelta(days=60),
                    "filters": {},
                },
                True,
            ),
        ]
    )
    def test_stale_filter_agrees_with_status_checker(
        self, key: str, flag_kwargs: dict[str, Any], expected_stale: bool
    ) -> None:
        FeatureFlag.objects.create(team=self.team, key=key, created_by=self.user, **flag_kwargs)

        filter_stale = self._filter("STALE")
        assert filter_stale == self._checker_stale()
        assert (key in filter_stale) is expected_stale

    def test_stale_filter_query_count_does_not_grow_with_candidate_count(self) -> None:
        def evaluate() -> list[FeatureFlag]:
            return list(filter_stale_flags(FeatureFlag.objects.filter(team=self.team)))

        with self.assertNumQueries(1):
            baseline = evaluate()

        FeatureFlag.objects.bulk_create(
            FeatureFlag(
                team=self.team,
                key=f"bulk-stale-{index}",
                active=True,
                created_at=timezone.now() - timedelta(days=60),
                filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
                created_by=self.user,
            )
            for index in range(20)
        )

        with self.assertNumQueries(1):
            expanded = evaluate()

        assert len(expanded) == len(baseline) + 20


class TestRolloutSummary(BaseTest):
    def _summary(self, filters):
        flag = FeatureFlag.objects.create(team=self.team, key="rollout-flag", filters=filters, created_by=self.user)
        return FeatureFlagStatusChecker(feature_flag=flag).get_rollout_summary(flag)

    # (name, filters, effectively_full_rollout, has_targeting_conditions, max_rollout_percentage, is_multivariate)
    @parameterized.expand(
        [
            (
                "blanket_full_rollout",
                {"groups": [{"properties": [], "rollout_percentage": 100}]},
                True,
                False,
                100,
                False,
            ),
            (
                "partial_rollout",
                {"groups": [{"properties": [], "rollout_percentage": 50}]},
                False,
                False,
                50,
                False,
            ),
            (
                "targeting_conditions",
                {"groups": [{"properties": [{"key": "email", "value": "x"}], "rollout_percentage": 100}]},
                False,
                True,
                100,
                False,
            ),
            # A missing rollout_percentage evaluates to 100% at runtime, so max_rollout_percentage
            # reflects that. effectively_full_rollout stays stricter (requires an explicit 100), to
            # match the staleness detection it shares logic with.
            ("missing_rollout_percentage", {"groups": [{"properties": []}]}, False, False, 100, False),
            # No release conditions means a boolean flag evaluates to true for everyone.
            ("no_groups", {"groups": []}, True, False, None, False),
            (
                "max_rollout_percentage_across_multiple_groups",
                {
                    "groups": [
                        {"properties": [{"key": "email", "value": "x"}], "rollout_percentage": 30},
                        {"properties": [], "rollout_percentage": 75},
                    ]
                },
                False,
                True,
                75,
                False,
            ),
            (
                "multivariate_fully_rolled_out",
                {
                    "multivariate": {"variants": [{"key": "control", "rollout_percentage": 100}]},
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                },
                True,
                False,
                100,
                True,
            ),
            (
                "multivariate_not_fully_rolled_out",
                {
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 50},
                            {"key": "test", "rollout_percentage": 50},
                        ]
                    },
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                },
                False,
                False,
                100,
                True,
            ),
            # An empty variant list is treated as a boolean flag, so a 100% blanket group is a full
            # rollout and is_multivariate is False — consistent with effectively_full_rollout.
            (
                "empty_multivariate_variants",
                {"multivariate": {"variants": []}, "groups": [{"properties": [], "rollout_percentage": 100}]},
                True,
                False,
                100,
                False,
            ),
        ]
    )
    def test_rollout_summary(
        self,
        _name,
        filters,
        effectively_full_rollout,
        has_targeting_conditions,
        max_rollout_percentage,
        is_multivariate,
    ):
        summary = self._summary(filters)
        assert summary.effectively_full_rollout is effectively_full_rollout
        assert summary.has_targeting_conditions is has_targeting_conditions
        assert summary.max_rollout_percentage == max_rollout_percentage
        assert summary.is_multivariate is is_multivariate

    def test_handles_none_filters(self):
        flag = FeatureFlag.objects.create(team=self.team, key="none-filters", created_by=self.user)
        flag.filters = None
        summary = FeatureFlagStatusChecker(feature_flag=flag).get_rollout_summary(flag)
        assert summary.effectively_full_rollout is True
        assert summary.max_rollout_percentage is None
        assert summary.is_multivariate is False
