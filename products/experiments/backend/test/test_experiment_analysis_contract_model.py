from typing import Any

from posthog.test.base import TestMigrations


class ExperimentDormantV2AnalysisColumnsMigrationTest(TestMigrations):
    migrate_from = "0036_alter_experimentmetricsrecalculation_trigger"
    migrate_to = "0037_experiment_dormant_v2_analysis_columns"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "experiments"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        FeatureFlag = apps.get_model("feature_flags", "FeatureFlag")
        Experiment = apps.get_model("experiments", "Experiment")

        org = Organization.objects.create(name="Test Organization")
        project = Project.objects.create(id=999995, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=project, name="Test Team")
        flag = FeatureFlag.objects.create(team=team, created_by=None, key="existing-experiment-flag")
        self.experiment_id = Experiment.objects.create(team=team, name="existing", feature_flag=flag).id

    def test_existing_row_is_null_in_every_new_column(self) -> None:
        # Guards the expansion step against a smuggled default or backfill: existing rows must stay
        # null until the dedicated backfill migration maps them to "v1".
        assert self.apps is not None
        Experiment = self.apps.get_model("experiments", "Experiment")

        experiment = Experiment.objects.get(id=self.experiment_id)
        assert experiment.feature_flag_rule_id is None
        assert experiment.analysis_contract is None
        assert experiment.analysis_snapshot is None
