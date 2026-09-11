import uuid
from typing import Any

from posthog.test.base import NonAtomicTestMigrations

from django.db import IntegrityError, connection, transaction


class ExperimentFeatureFlagRuleIdUniqueMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0039_experiment_dormant_v2_analysis_columns"
    migrate_to = "0040_experiment_feature_flag_rule_id_unique"

    @property
    def app(self) -> str:
        return "experiments"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Experiment = apps.get_model("experiments", "Experiment")
        FeatureFlag = apps.get_model("feature_flags", "FeatureFlag")
        self.flag_id = FeatureFlag.objects.create(team_id=self.team.pk, created_by=None, key="existing-flag").pk
        self.experiment_ids = [
            Experiment.objects.create(team_id=self.team.pk, name=name, feature_flag_id=self.flag_id).id
            for name in ("first", "second")
        ]

    def test_partial_unique_index_keeps_null_rows_and_rejects_duplicate_rule_ids(self) -> None:
        assert self.apps is not None
        Experiment = self.apps.get_model("experiments", "Experiment")

        surviving = Experiment.objects.filter(id__in=self.experiment_ids, feature_flag_rule_id__isnull=True)
        assert surviving.count() == 2

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexdef FROM pg_indexes WHERE tablename = 'posthog_experiment' AND indexname = %s",
                ["posthog_experiment_feature_flag_rule_id_uniq"],
            )
            (indexdef,) = cursor.fetchone()
        assert indexdef.startswith("CREATE UNIQUE INDEX")
        assert indexdef.endswith("WHERE (feature_flag_rule_id IS NOT NULL)")

        rule_id = uuid.uuid4()
        Experiment.objects.create(
            team_id=self.team.pk, name="v2", feature_flag_id=self.flag_id, feature_flag_rule_id=rule_id
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Experiment.objects.create(
                team_id=self.team.pk, name="duplicate", feature_flag_id=self.flag_id, feature_flag_rule_id=rule_id
            )

        Experiment.objects.create(team_id=self.team.pk, name="third-null", feature_flag_id=self.flag_id)
        assert Experiment.objects.filter(feature_flag_rule_id__isnull=True).count() == 3
