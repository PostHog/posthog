from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import serializers

from products.early_access_features.backend.models import EarlyAccessFeature
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.ownership import FLAG_OWNER_SURVEY, assert_flag_available_for, flag_owner_kind
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey


class TestFlagOwnership(APIBaseTest):
    def _flag(self, key: str) -> FeatureFlag:
        return FeatureFlag.objects.create(team=self.team, key=key, name=key, created_by=self.user)

    def _own_by_experiment(self, flag: FeatureFlag) -> None:
        Experiment.objects.create(team=self.team, name="exp", feature_flag=flag)

    def _own_by_survey_targeting(self, flag: FeatureFlag) -> None:
        Survey.objects.create(team=self.team, name="s", type="popover", targeting_flag=flag)

    def _own_by_survey_internal(self, flag: FeatureFlag) -> None:
        Survey.objects.create(team=self.team, name="s", type="popover", internal_targeting_flag=flag)

    def _own_by_survey_sampling(self, flag: FeatureFlag) -> None:
        Survey.objects.create(team=self.team, name="s", type="popover", internal_response_sampling_flag=flag)

    def _own_by_product_tour(self, flag: FeatureFlag) -> None:
        ProductTour.objects.create(team=self.team, name="t", internal_targeting_flag=flag)

    def _own_by_archived_product_tour(self, flag: FeatureFlag) -> None:
        ProductTour.objects.create(team=self.team, name="t", internal_targeting_flag=flag, archived=True)

    def _own_by_deleted_experiment(self, flag: FeatureFlag) -> None:
        Experiment.objects.create(team=self.team, name="exp", feature_flag=flag, deleted=True)

    def _own_by_early_access(self, flag: FeatureFlag) -> None:
        EarlyAccessFeature.objects.create(team=self.team, name="f", stage="beta", feature_flag=flag)

    def _reference_by_survey_linked_flag(self, flag: FeatureFlag) -> None:
        Survey.objects.create(team=self.team, name="s", type="popover", linked_flag=flag)

    @parameterized.expand(
        [
            ("experiment", "_own_by_experiment", "experiment"),
            ("survey targeting flag", "_own_by_survey_targeting", "survey"),
            ("survey internal flag", "_own_by_survey_internal", "survey"),
            ("survey sampling flag", "_own_by_survey_sampling", "survey"),
            ("product tour", "_own_by_product_tour", "product_tour"),
            ("archived product tour", "_own_by_archived_product_tour", "product_tour"),
            ("early access feature", "_own_by_early_access", "early_access_feature"),
            ("deleted experiment", "_own_by_deleted_experiment", "experiment"),
            ("survey linked flag", "_reference_by_survey_linked_flag", None),
            ("nothing", None, None),
        ]
    )
    def test_flag_owner_kind(self, name: str, setup: str | None, expected: str | None) -> None:
        flag = self._flag(f"owned-by-{name.replace(' ', '-')}")
        if setup:
            getattr(self, setup)(flag)

        assert flag_owner_kind(flag) == expected

    def test_guard_rejects_a_flag_a_different_product_owns(self) -> None:
        flag = self._flag("taken")
        self._own_by_experiment(flag)

        with self.assertRaises(serializers.ValidationError) as cm:
            assert_flag_available_for(flag, product=FLAG_OWNER_SURVEY)

        assert "already belongs to an experiment" in str(cm.exception)

    def test_guard_allows_a_free_flag(self) -> None:
        assert_flag_available_for(self._flag("free"), product=FLAG_OWNER_SURVEY)

    def test_guard_allows_the_same_product_to_share_a_flag(self) -> None:
        flag = self._flag("shared")
        self._own_by_experiment(flag)

        assert_flag_available_for(flag, product="experiment")


class TestSurveyFlagAdoptionGuard(APIBaseTest):
    def test_survey_cannot_adopt_a_flag_another_product_owns(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="experiment-flag", created_by=self.user)
        Experiment.objects.create(team=self.team, name="exp", feature_flag=flag)

        response = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={"name": "poacher", "type": "popover", "targeting_flag_id": flag.id},
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert "already belongs to an experiment" in str(response.json())

    def test_survey_cannot_be_repointed_at_a_flag_another_product_owns(self) -> None:
        created = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={"name": "plain", "type": "popover"},
            format="json",
        )
        assert created.status_code == 201, created.json()

        flag = FeatureFlag.objects.create(team=self.team, key="taken-by-experiment", created_by=self.user)
        Experiment.objects.create(team=self.team, name="exp", feature_flag=flag)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{created.json()['id']}/",
            data={"targeting_flag_id": flag.id},
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert "already belongs to an experiment" in str(response.json())

    def test_survey_can_be_saved_again_with_the_flag_it_already_owns(self) -> None:
        created = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "targeted",
                "type": "popover",
                "targeting_flag_filters": {"groups": [{"variant": None, "rollout_percentage": 50, "properties": []}]},
            },
            format="json",
        )
        assert created.status_code == 201, created.json()
        survey = Survey.objects.get(id=created.json()["id"])
        assert survey.targeting_flag_id is not None

        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={"targeting_flag_id": survey.targeting_flag_id, "name": "renamed"},
            format="json",
        )

        assert response.status_code == 200, response.json()
