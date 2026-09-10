from typing import Any

from posthog.test.base import TestMigrations

from products.feature_flags.backend.models import FeatureFlag


class ExperimentDormantV2AnalysisColumnsMigrationTest(TestMigrations):
    migrate_from = "0037_squash_2026_09_07_finalize_fks"
    migrate_to = "0038_experiment_dormant_v2_analysis_columns"

    @property
    def app(self) -> str:
        return "experiments"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Experiment = apps.get_model("experiments", "Experiment")
        flag = FeatureFlag.objects.create(team=self.team, created_by=None, key="existing-experiment-flag")
        self.experiment_id = Experiment.objects.create(
            team_id=self.team.pk, name="existing", feature_flag_id=flag.pk
        ).id

    def test_existing_row_is_null_in_every_new_column(self) -> None:
        assert self.apps is not None
        Experiment = self.apps.get_model("experiments", "Experiment")

        experiment = Experiment.objects.get(id=self.experiment_id)
        assert experiment.feature_flag_rule_id is None
        assert experiment.analysis_snapshot is None
