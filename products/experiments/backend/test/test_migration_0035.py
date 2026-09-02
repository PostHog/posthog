from typing import Any

from posthog.test.base import TestMigrations


class StripUnknownExposureCriteriaKeysMigrationTest(TestMigrations):
    migrate_from = "0034_backfill_precomputation_enabled_set_by"
    migrate_to = "0035_strip_unknown_exposure_criteria_keys"

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
        project = Project.objects.create(id=999996, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=project, name="Test Team")

        def make_experiment(name: str, exposure_criteria: dict | None) -> Any:
            flag = FeatureFlag.objects.create(team=team, created_by=None, key=f"flag-{name}")
            return Experiment.objects.create(
                team=team, name=name, feature_flag=flag, exposure_criteria=exposure_criteria
            )

        self.stray_properties_id = make_experiment(
            "stray-properties",
            {"filterTestAccounts": True, "properties": [{"key": "email", "value": "x"}]},
        ).id
        self.config_at_criteria_level_id = make_experiment(
            "config-at-criteria-level",
            {"kind": "ExperimentEventExposureConfig", "event": "$pageview", "properties": []},
        ).id
        self.valid_id = make_experiment(
            "valid",
            {
                "filterTestAccounts": False,
                "exposure_config": {"event": "$pageview", "properties": []},
                "multiple_variant_handling": "exclude",
            },
        ).id
        self.null_id = make_experiment("null-criteria", None).id

    def test_strips_only_unknown_keys(self) -> None:
        assert self.apps is not None
        Experiment = self.apps.get_model("experiments", "Experiment")

        assert Experiment.objects.get(id=self.stray_properties_id).exposure_criteria == {"filterTestAccounts": True}
        assert Experiment.objects.get(id=self.config_at_criteria_level_id).exposure_criteria == {}
        assert Experiment.objects.get(id=self.valid_id).exposure_criteria == {
            "filterTestAccounts": False,
            "exposure_config": {"event": "$pageview", "properties": []},
            "multiple_variant_handling": "exclude",
        }
        assert Experiment.objects.get(id=self.null_id).exposure_criteria is None
