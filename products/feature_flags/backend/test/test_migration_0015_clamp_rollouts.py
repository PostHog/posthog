from typing import Any

from posthog.test.base import BaseTest, TestMigrations
from unittest.mock import patch

from django.apps import apps as global_apps
from django.db import connection
from django.test.utils import CaptureQueriesContext


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
        self.annotated_id = make_flag(
            "annotated",
            {
                "groups": [{"properties": [], "rollout_percentage": 100, "variant": None}],
                "multivariate": {
                    "variants": [
                        {"key": "v0", "name": "First", "rollout_percentage": 40},
                        {"key": "v1", "name": "Second", "rollout_percentage": 40},
                        {"key": "v2", "name": "Third", "rollout_percentage": 40},
                    ],
                    "some_unrelated_key": "kept",
                },
                "payloads": {"v0": "1"},
            },
        ).id
        self.two_over_id = make_flag("two-over", {"groups": [], "multivariate": variants(60, 60)}).id
        # Decimal inputs whose remainder lands whole: the only shape where the int conversion
        # changes the stored value, 33.0 without it and 33 with it.
        self.whole_remainder_id = make_flag(
            "whole-remainder", {"groups": [], "multivariate": variants(33.5, 33.5, 50)}
        ).id
        self.drifting_remainder_id = make_flag(
            "drifting-remainder", {"groups": [], "multivariate": variants(10.1, 20.2, 30.3, 50.5)}
        ).id
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

        # Clamping a [40, 100] shape flips has_hash_dependent_variants, which starts the
        # continuity override lookup and can change which identifier is hashed.
        self.risky_with_continuity_id = make_flag(
            "risky-with-continuity",
            {"groups": [], "multivariate": variants(40, 100)},
            ensure_experience_continuity=True,
        ).id
        self.risky_without_continuity_id = make_flag(
            "risky-without-continuity", {"groups": [], "multivariate": variants(40, 100)}
        ).id
        self.leading_full_with_continuity_id = make_flag(
            "leading-full-with-continuity",
            {"groups": [], "multivariate": variants(100, 40)},
            ensure_experience_continuity=True,
        ).id

        # Past the first 500-row batch, so keyset pagination is actually exercised.
        for i in range(505):
            make_flag(f"filler-{i}", {"groups": [], "multivariate": variants(50, 50)})
        self.last_batch_id = make_flag("last-batch", {"groups": [], "multivariate": variants(80, 80)}).id

        # Shapes the scan must skip rather than raise on.
        self.junk = {
            "filters-not-dict": make_flag("junk-filters-not-dict", {}).id,
            "multivariate-list": make_flag("junk-multivariate-list", {"groups": [], "multivariate": ["nope"]}).id,
            "variants-not-list": make_flag(
                "junk-variants-not-list", {"groups": [], "multivariate": {"variants": {}}}
            ).id,
            "variant-entry": make_flag("junk-variant-entry", {"groups": [], "multivariate": {"variants": ["nope"]}}).id,
            "rollout-string": make_flag("junk-rollout-string", {"groups": [], "multivariate": variants("60", "60")}).id,
            "no-multivariate": make_flag("no-multivariate", {"groups": []}).id,
            "rollout-bool": make_flag("junk-rollout-bool", {"groups": [], "multivariate": variants(True, 100)}).id,
        }
        # A whole `filters` value that is not a dict at all; the model default blocks it on create.
        FeatureFlag.objects.filter(id=self.junk["filters-not-dict"]).update(filters=["nope"])

    def _raw_filters(self, flag_id: int) -> Any:
        assert self.apps is not None
        FeatureFlag = self.apps.get_model("feature_flags", "FeatureFlag")
        return FeatureFlag.objects.get(id=flag_id).filters

    def _filters(self, flag_id: int) -> dict:
        assert self.apps is not None
        FeatureFlag = self.apps.get_model("feature_flags", "FeatureFlag")
        return FeatureFlag.objects.get(id=flag_id).filters

    def test_preserves_every_other_field_while_clamping(self) -> None:
        assert self._filters(self.annotated_id) == {
            "groups": [{"properties": [], "rollout_percentage": 100, "variant": None}],
            "multivariate": {
                "variants": [
                    {"key": "v0", "name": "First", "rollout_percentage": 40},
                    {"key": "v1", "name": "Second", "rollout_percentage": 40},
                    {"key": "v2", "name": "Third", "rollout_percentage": 20},
                ],
                "some_unrelated_key": "kept",
            },
            "payloads": {"v0": "1"},
        }

    def test_skips_only_the_shape_that_flips_hash_dependence_with_continuity(self) -> None:
        # Continuity on plus a 100 after a smaller variant: the one shape that can move a user.
        assert rollouts(self._filters(self.risky_with_continuity_id)) == [40, 100]
        # Same shape without continuity hashes the distinct_id either way, so it is safe.
        assert rollouts(self._filters(self.risky_without_continuity_id)) == [40, 60]
        # The 100 comes first, so nothing smaller precedes it and the classification is unchanged.
        assert rollouts(self._filters(self.leading_full_with_continuity_id)) == [100, 0]

    def test_clamps_rows_past_the_first_batch(self) -> None:
        assert rollouts(self._filters(self.last_batch_id)) == [80, 20]

    def test_clamps_a_straddling_variant_to_the_remainder(self) -> None:
        assert rollouts(self._filters(self.straddling_id)) == [40, 40, 20]
        assert rollouts(self._filters(self.two_over_id)) == [60, 40]

    def test_zeroes_variants_the_evaluator_can_never_reach(self) -> None:
        assert rollouts(self._filters(self.first_takes_all_id)) == [100, 0]
        assert rollouts(self._filters(self.unreachable_id)) == [50, 50, 0]

    def test_keeps_whole_numbers_as_integers(self) -> None:
        # A float here would re-break the .NET and Java SDKs that #84957 fixed. The decimal
        # fixture is the one that pins the conversion: its remainder is whole, so without it
        # the stored value would be 33.0.
        assert [type(r) for r in rollouts(self._filters(self.straddling_id))] == [int, int, int]
        assert rollouts(self._filters(self.whole_remainder_id)) == [33.5, 33.5, 33]
        assert [type(r) for r in rollouts(self._filters(self.whole_remainder_id))] == [float, float, int]

    def test_rounds_the_remainder_instead_of_storing_a_float_artifact(self) -> None:
        assert rollouts(self._filters(self.drifting_remainder_id)) == [10.1, 20.2, 30.3, 39.4]

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
        assert self._raw_filters(self.junk["filters-not-dict"]) == ["nope"]
        assert self._filters(self.junk["multivariate-list"])["multivariate"] == ["nope"]
        assert self._filters(self.junk["variants-not-list"])["multivariate"]["variants"] == {}
        assert self._filters(self.junk["variant-entry"])["multivariate"]["variants"] == ["nope"]
        assert rollouts(self._filters(self.junk["rollout-string"])) == ["60", "60"]
        assert "multivariate" not in self._filters(self.junk["no-multivariate"])
        # True is an int in Python, so without the bool guard this would become [1, 99].
        assert rollouts(self._filters(self.junk["rollout-bool"])) == [True, 100]


class ClampRolloutCompareAndSwapTest(BaseTest):
    """The `filters=flag.filters` predicate is what stops a stale snapshot overwriting a newer
    edit, and only a write landing mid-scan exercises it."""

    def test_a_write_landing_mid_scan_survives(self) -> None:
        from importlib import import_module

        from products.feature_flags.backend.models.feature_flag import FeatureFlag

        migration = import_module("products.feature_flags.backend.migrations.0015_clamp_rollout_percentages_over_100")
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="raced",
            filters={"groups": [], "multivariate": variants(60, 60)},
        )
        edited = {"groups": [], "multivariate": variants(25, 25)}

        original_clamp = migration._clamp_filters

        def clamp_then_race(filters: dict, has_continuity: bool) -> dict | None:
            result = original_clamp(filters, has_continuity)
            if result is not None:
                # Stand in for a user saving between the batch SELECT and the UPDATE.
                FeatureFlag.objects.filter(id=flag.id).update(filters=edited)
            return result

        with patch.object(migration, "_clamp_filters", clamp_then_race):
            migration.clamp_rollout_percentages_over_100(global_apps, None)

        flag.refresh_from_db()
        assert flag.filters == edited


class ClampRolloutQueryCountTest(BaseTest):
    """The scan reads `ensure_experience_continuity`, so it has to be in the `.only()`. Without
    it Django refetches the column once per row, and the field has silently dropped out once."""

    def test_the_scan_does_not_query_per_row(self) -> None:
        from importlib import import_module

        from products.feature_flags.backend.models.feature_flag import FeatureFlag

        migration = import_module("products.feature_flags.backend.migrations.0015_clamp_rollout_percentages_over_100")
        for i in range(25):
            FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key=f"counted-{i}",
                filters={
                    "groups": [],
                    "multivariate": {
                        "variants": [
                            {"key": "a", "name": "", "rollout_percentage": 60},
                            {"key": "b", "name": "", "rollout_percentage": 60},
                        ]
                    },
                },
            )

        with CaptureQueriesContext(connection) as captured:
            migration.clamp_rollout_percentages_over_100(global_apps, None)

        selects = [q["sql"] for q in captured.captured_queries if q["sql"].lstrip().upper().startswith("SELECT")]
        # One batch of up to 500, then one empty batch that ends the loop. A per-row refetch
        # would add one SELECT for every flag scanned.
        assert len(selects) == 2, "\n".join(selects)
