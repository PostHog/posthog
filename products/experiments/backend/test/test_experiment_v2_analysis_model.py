from typing import Any

from posthog.test.base import TestMigrations


class ExperimentDormantV2AnalysisColumnsMigrationTest(TestMigrations):
    migrate_from = "0038_alter_experimentholdout_created_by_and_more"
    migrate_to = "0039_experiment_dormant_v2_analysis_columns"

    @property
    def app(self) -> str:
        return "experiments"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Experiment = apps.get_model("experiments", "Experiment")
        FeatureFlag = apps.get_model("feature_flags", "FeatureFlag")
        flag = FeatureFlag.objects.create(team_id=self.team.pk, created_by=None, key="existing-experiment-flag")
        self.experiment_id = Experiment.objects.create(
            team_id=self.team.pk, name="existing", feature_flag_id=flag.pk
        ).id

    def test_existing_row_is_null_in_every_new_column(self) -> None:
        assert self.apps is not None
        Experiment = self.apps.get_model("experiments", "Experiment")

        experiment = Experiment.objects.get(id=self.experiment_id)
        assert experiment.feature_flag_rule_id is None
        assert experiment.feature_flag_rule_snapshot is None
