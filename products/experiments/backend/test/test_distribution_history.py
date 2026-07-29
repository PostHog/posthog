from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone

from products.experiments.backend.distribution_history import variant_split_changed_at
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.facade.api import update_flag
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _filters(control: int, test: int, rollout: int = 100) -> dict:
    return {
        "groups": [{"properties": [], "rollout_percentage": rollout}],
        "multivariate": {
            "variants": [
                {"key": "control", "name": "Control", "rollout_percentage": control},
                {"key": "test", "name": "Test", "rollout_percentage": test},
            ]
        },
    }


class TestVariantSplitChangedAt(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="split-flag",
            name="Split flag",
            filters=_filters(50, 50),
        )
        self.launched_at = timezone.now() - timedelta(days=1)
        self.experiment = Experiment.objects.create(
            team=self.team,
            name="Split experiment",
            feature_flag=self.flag,
            start_date=self.launched_at,
        )

    def _update_filters(self, filters: dict) -> None:
        update_flag(self.flag, {"filters": filters}, team=self.team, user=self.user)
        self.flag.refresh_from_db()

    def test_no_change_after_launch(self) -> None:
        assert variant_split_changed_at(self.experiment) is None

    def test_draft_experiment_is_never_flagged(self) -> None:
        self.experiment.start_date = None
        self._update_filters(_filters(70, 30))

        assert variant_split_changed_at(self.experiment) is None

    def test_split_change_after_launch_is_reported(self) -> None:
        self._update_filters(_filters(70, 30))

        changed_at = variant_split_changed_at(self.experiment)

        assert changed_at is not None
        assert changed_at > self.launched_at

    def test_split_change_before_launch_is_ignored(self) -> None:
        self._update_filters(_filters(70, 30))
        self.experiment.start_date = timezone.now()

        assert variant_split_changed_at(self.experiment) is None

    def test_overall_rollout_change_is_not_a_split_change(self) -> None:
        # A different hash salt gates the rollout, so raising it admits new users without
        # moving anyone between variants.
        self._update_filters(_filters(50, 50, rollout=60))

        assert variant_split_changed_at(self.experiment) is None

    def test_reports_the_first_of_several_changes(self) -> None:
        self._update_filters(_filters(70, 30))
        first_change = variant_split_changed_at(self.experiment)
        self._update_filters(_filters(60, 40))

        assert variant_split_changed_at(self.experiment) == first_change

    def test_change_after_the_experiment_ended_is_ignored(self) -> None:
        self.experiment.end_date = timezone.now()
        self._update_filters(_filters(70, 30))

        assert variant_split_changed_at(self.experiment) is None

    def test_another_flags_change_is_ignored(self) -> None:
        other_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="other-flag",
            name="Other flag",
            filters=_filters(50, 50),
        )
        update_flag(other_flag, {"filters": _filters(70, 30)}, team=self.team, user=self.user)

        assert variant_split_changed_at(self.experiment) is None
