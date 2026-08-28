from posthog.test.base import BaseTest

from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _variants(*keys: str) -> list[dict]:
    return [{"key": key, "rollout_percentage": 100 if len(keys) == 1 else 0} for key in keys]


class TestExperimentEligibility(BaseTest):
    # (key, multivariate variants or None, eligible) — multivariate with 2-20 variants;
    # no 'control' variant is required (the baseline defaults downstream).
    CASES = [
        ("boolean-flag", None, False),
        ("single-variant", _variants("control"), False),
        ("control-first", _variants("control", "test"), True),
        ("control-not-first", _variants("test", "control"), True),
        ("control-missing", _variants("test-1", "test-2"), True),
        ("twenty-variants", _variants("control", *[f"test-{i}" for i in range(19)]), True),
        ("twenty-one-variants", _variants("control", *[f"test-{i}" for i in range(20)]), False),
    ]

    def test_queryset_and_predicate_agree_on_eligibility(self):
        for key, variants, _ in self.CASES:
            filters = {"groups": []} if variants is None else {"groups": [], "multivariate": {"variants": variants}}
            FeatureFlag.objects.create(team=self.team, key=key, created_by=self.user, filters=filters)

        eligible_keys = set(
            FeatureFlag.objects.filter(team=self.team).eligible_for_experiment().values_list("key", flat=True)
        )
        assert eligible_keys == {key for key, _, eligible in self.CASES if eligible}

        for key, _, eligible in self.CASES:
            flag = FeatureFlag.objects.get(team=self.team, key=key)
            assert flag.is_eligible_for_experiment is eligible, key


class TestFeatureFlagManager(BaseTest):
    def test_default_manager_excludes_soft_deleted_flags(self):
        FeatureFlag.objects.create(team=self.team, key="live", created_by=self.user)
        deleted_flag = FeatureFlag.objects_including_soft_deleted.create(
            team=self.team, key="deleted", created_by=self.user, deleted=True
        )

        assert FeatureFlag.objects.filter(team=self.team).count() == 1
        assert FeatureFlag.objects_including_soft_deleted.filter(team=self.team).count() == 2

        with self.assertRaises(FeatureFlag.DoesNotExist):
            FeatureFlag.objects.get(pk=deleted_flag.pk)
        assert FeatureFlag.objects_including_soft_deleted.get(pk=deleted_flag.pk) == deleted_flag

    def test_filters_default_includes_groups_key(self):
        flag = FeatureFlag.objects.create(team=self.team, key="default-filters", created_by=self.user)
        flag.refresh_from_db()
        assert flag.filters == {"groups": []}
