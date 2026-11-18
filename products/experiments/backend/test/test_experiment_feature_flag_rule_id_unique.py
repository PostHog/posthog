import uuid

from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestExperimentFeatureFlagRuleIdUnique(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = FeatureFlag.objects.create(team=self.team, key="rule-id-unique", created_by=self.user)

    def _create(self, rule_id: uuid.UUID | None = None) -> Experiment:
        return Experiment.objects.create(
            team=self.team, name="experiment", feature_flag=self.flag, feature_flag_rule_id=rule_id
        )

    def test_duplicate_rule_id_is_rejected_and_null_rows_are_not(self) -> None:
        rule_id = uuid.uuid4()
        self._create(rule_id)

        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            self._create(rule_id)
        assert 'unique constraint "posthog_experiment_feature_flag_rule_id_uniq"' in str(caught.exception)

        # Legacy experiments keep the column null; the partial index must not treat them as duplicates.
        self._create()
        self._create()
