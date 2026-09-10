from datetime import UTC, datetime

from posthog.test.base import BaseTest

from posthog.models.team import Team

from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.replay_linkage import targetable_experiments
from products.feature_flags.backend.models.feature_flag import FeatureFlag


# The read a surface uses to offer experiments before it has a query to run. It has to refuse
# exactly what `resolve_exposure_linkage` refuses, or a surface offers a target whose exposure
# filter fails the moment a query resolves it.
class TestTargetableExperiments(BaseTest):
    def _flag(self, key: str, *, variants: list[dict] | None = None, group_index: int | None = None) -> FeatureFlag:
        filters: dict = {}
        if variants is not None:
            filters["multivariate"] = {"variants": variants}
        if group_index is not None:
            filters["aggregation_group_type_index"] = group_index
        return FeatureFlag.objects.create(team=self.team, key=key, name=key, created_by=self.user, filters=filters)

    def _experiment(self, name: str, *, flag: FeatureFlag, launched: bool = True, **kwargs) -> Experiment:
        return Experiment.objects.create(
            team=self.team,
            name=name,
            feature_flag=flag,
            created_by=self.user,
            start_date=datetime(2026, 1, 1, tzinfo=UTC) if launched else None,
            exposure_criteria={},
            **kwargs,
        )

    def _default_variants(self) -> list[dict]:
        return [
            {"key": "control", "rollout_percentage": 50},
            {"key": "test", "rollout_percentage": 50},
        ]

    def test_a_launched_experiment_comes_back_with_its_variants(self):
        experiment = self._experiment(
            "Checkout CTA copy", flag=self._flag("checkout-cta", variants=self._default_variants())
        )

        targetable = targetable_experiments(self.team, experiment_ids=[experiment.id])

        assert [(t.id, t.name, t.variants) for t in targetable] == [
            (experiment.id, "Checkout CTA copy", ("control", "test"))
        ]

    def test_an_excluded_variant_is_not_offered(self):
        # Asking for an excluded variant is refused when the exposure filter resolves, so it must
        # not be one of the keys a caller can pick.
        experiment = self._experiment(
            "Checkout CTA copy",
            flag=self._flag("checkout-cta", variants=self._default_variants()),
            excluded_variants=["control"],
        )

        assert targetable_experiments(self.team, experiment_ids=[experiment.id])[0].variants == ("test",)

    def test_an_experiment_the_exposure_filter_would_refuse_is_left_out(self):
        # Each of these raises in `resolve_exposure_linkage`, so offering it would hand a caller
        # targeting that only fails later.
        draft = self._experiment(
            "Not launched", flag=self._flag("not-launched", variants=self._default_variants()), launched=False
        )
        grouped = self._experiment(
            "Group aggregated", flag=self._flag("grouped", variants=self._default_variants(), group_index=0)
        )
        boolean = self._experiment("Boolean flag", flag=self._flag("boolean-flag"))
        deleted = self._experiment(
            "Deleted", flag=self._flag("deleted-exp", variants=self._default_variants()), deleted=True
        )

        targetable = targetable_experiments(self.team, experiment_ids=[draft.id, grouped.id, boolean.id, deleted.id])

        assert targetable == []

    def test_an_experiment_in_another_team_is_left_out(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        flag = FeatureFlag.objects.create(
            team=other_team,
            key="checkout-cta",
            name="checkout-cta",
            created_by=self.user,
            filters={"multivariate": {"variants": self._default_variants()}},
        )
        foreign = Experiment.objects.create(
            team=other_team,
            name="Checkout CTA copy",
            feature_flag=flag,
            created_by=self.user,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            exposure_criteria={},
        )

        assert targetable_experiments(self.team, experiment_ids=[foreign.id]) == []
