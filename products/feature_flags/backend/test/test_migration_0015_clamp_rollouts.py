from typing import Any

from posthog.test.base import TestMigrations


def variants(*percentages: Any) -> dict:
    return {"variants": [{"key": f"v{i}", "name": "", "rollout_percentage": p} for i, p in enumerate(percentages)]}


def rollouts(filters: dict) -> list:
    return [variant["rollout_percentage"] for variant in filters["multivariate"]["variants"]]


class ClampRolloutPercentagesMigrationTest(TestMigrations):
    migrate_from = "0014_clean_flag_filters_inert_violations"
    migrate_to = "0015_clamp_rollout_percentages_over_100"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "feature_flags"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        FeatureFlag = apps.get_model("feature_flags", "FeatureFlag")

        org = Organization.objects.create(name="Test Organization")
        project = Project.objects.create(id=999994, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=project, name="Test Team")

        def make_flag(key: str, filters: dict, **kwargs: Any) -> Any:
            return FeatureFlag.objects.create(team=team, created_by=None, key=key, filters=filters, **kwargs)

        self.straddling_id = make_flag("straddling", {"groups": [], "multivariate": variants(40, 40, 40)}).id
        self.two_over_id = make_flag("two-over", {"groups": [], "multivariate": variants(60, 60)}).id
        self.first_takes_all_id = make_flag("first-takes-all", {"groups": [], "multivariate": variants(150, 10)}).id
        self.unreachable_id = make_flag("unreachable", {"groups": [], "multivariate": variants(50, 50, 50)}).id
        self.fractional_id = make_flag("fractional", {"groups": [], "multivariate": variants(33.33, 33.33, 50)}).id
        self.soft_deleted_id = make_flag(
            "soft-deleted", {"groups": [], "multivariate": variants(70, 70)}, deleted=True
        ).id
        self.inactive_id = make_flag("inactive", {"groups": [], "multivariate": variants(70, 70)}, active=False).id
        self.encrypted_id = make_flag(
            "encrypted", {"groups": [], "multivariate": variants(60, 60)}, has_encrypted_payloads=True
        ).id

        # Left alone: already correct, or a shortfall only the customer can resolve.
        self.exact_id = make_flag("exact", {"groups": [], "multivariate": variants(40, 40, 20)}).id
        self.under_id = make_flag("under", {"groups": [], "multivariate": variants(30, 30)}).id
        self.drifting_id = make_flag("drifting", {"groups": [], "multivariate": variants(0.01, 64.04, 35.95)}).id

        # Shapes the scan must skip rather than raise on.
        self.junk_ids = [
            make_flag("junk-multivariate-list", {"groups": [], "multivariate": ["nope"]}).id,
            make_flag("junk-variants-not-list", {"groups": [], "multivariate": {"variants": {}}}).id,
            make_flag("junk-variant-entry", {"groups": [], "multivariate": {"variants": ["nope"]}}).id,
            make_flag("junk-rollout-string", {"groups": [], "multivariate": variants("60", "60")}).id,
            make_flag("no-multivariate", {"groups": []}).id,
        ]

    def _filters(self, flag_id: int) -> dict:
        assert self.apps is not None
        FeatureFlag = self.apps.get_model("feature_flags", "FeatureFlag")
        return FeatureFlag.objects.get(id=flag_id).filters

    def test_clamps_a_straddling_variant_to_the_remainder(self) -> None:
        assert rollouts(self._filters(self.straddling_id)) == [40, 40, 20]
        assert rollouts(self._filters(self.two_over_id)) == [60, 40]

    def test_zeroes_variants_the_evaluator_can_never_reach(self) -> None:
        assert rollouts(self._filters(self.first_takes_all_id)) == [100, 0]
        assert rollouts(self._filters(self.unreachable_id)) == [50, 50, 0]

    def test_keeps_whole_numbers_as_integers(self) -> None:
        # A float here would re-break the .NET and Java SDKs that #84957 fixed.
        assert [type(r) for r in rollouts(self._filters(self.straddling_id))] == [int, int, int]

    def test_keeps_real_decimals(self) -> None:
        assert rollouts(self._filters(self.fractional_id)) == [33.33, 33.33, 33.34]

    def test_covers_soft_deleted_inactive_and_encrypted_flags(self) -> None:
        assert rollouts(self._filters(self.soft_deleted_id)) == [70, 30]
        assert rollouts(self._filters(self.inactive_id)) == [70, 30]
        assert rollouts(self._filters(self.encrypted_id)) == [60, 40]

    def test_leaves_correct_and_short_sums_alone(self) -> None:
        assert rollouts(self._filters(self.exact_id)) == [40, 40, 20]
        assert rollouts(self._filters(self.under_id)) == [30, 30]
        assert rollouts(self._filters(self.drifting_id)) == [0.01, 64.04, 35.95]

    def test_skips_malformed_filters_without_raising(self) -> None:
        # Reaching any assertion here means the scan completed; these rows stay as they were.
        assert self._filters(self.junk_ids[0])["multivariate"] == ["nope"]
        assert self._filters(self.junk_ids[2])["multivariate"]["variants"] == ["nope"]
        assert rollouts(self._filters(self.junk_ids[3])) == ["60", "60"]
        assert "multivariate" not in self._filters(self.junk_ids[4])
