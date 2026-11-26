from posthog.test.base import BaseTest

from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _variants(*keys: str) -> list[dict]:
    return [{"key": key, "rollout_percentage": 100 if len(keys) == 1 else 0} for key in keys]


def _v1_filters(variants: list[dict] | None) -> dict:
    return {"groups": []} if variants is None else {"groups": [], "multivariate": {"variants": variants}}


def _rule(rule_type: str, variant_count: int = 0) -> dict:
    rule: dict = {"id": f"rule-{rule_type}-{variant_count}", "rule_type": rule_type, "targeting": {"properties": []}}
    if rule_type == "experiment":
        rule["variants"] = [{"key": f"v{i}", "weight": 100 if i == 0 else 0, "value": i} for i in range(variant_count)]
    else:
        rule["value"] = True
    return rule


def _v2_filters(*rules: dict) -> dict:
    return {"version": 2, "return_type": "number", "default_value": 0, "rules": list(rules)}


class TestExperimentEligibility(BaseTest):
    # (key, filters, eligible); no 'control' variant is required (the baseline defaults downstream).
    CASES = [
        ("boolean-flag", _v1_filters(None), False),
        ("single-variant", _v1_filters(_variants("control")), False),
        ("control-first", _v1_filters(_variants("control", "test")), True),
        ("control-not-first", _v1_filters(_variants("test", "control")), True),
        ("control-missing", _v1_filters(_variants("test-1", "test-2")), True),
        ("twenty-variants", _v1_filters(_variants("control", *[f"test-{i}" for i in range(19)])), True),
        ("twenty-one-variants", _v1_filters(_variants("control", *[f"test-{i}" for i in range(20)])), False),
        ("rules-without-experiment-rule", _v2_filters(_rule("targeted_release"), _rule("percentage_rollout")), False),
        ("rules-with-experiment-rule", _v2_filters(_rule("targeted_release"), _rule("experiment", 2)), True),
        ("rules-with-twenty-variants", _v2_filters(_rule("experiment", 20)), True),
        ("rules-with-one-variant", _v2_filters(_rule("experiment", 1)), False),
        ("rules-with-twenty-one-variants", _v2_filters(_rule("experiment", 21)), False),
        ("rules-with-one-eligible-rule", _v2_filters(_rule("experiment", 1), _rule("experiment", 3)), True),
        ("rules-without-rules", _v2_filters(), False),
        # Only a config version 2 document has rules, so a v1 document carrying a rules key is read as v1.
        ("v1-with-a-rules-key", {**_v1_filters(None), "rules": [_rule("experiment", 2)]}, False),
    ]

    def test_queryset_and_predicate_agree_on_eligibility(self):
        for key, filters, _ in self.CASES:
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
