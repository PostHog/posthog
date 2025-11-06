from rest_framework import status

from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag

from products.enterprise.backend.api.test.base import APILicensedTest


class TestExperimentHoldoutCRUD(APILicensedTest):
    def test_can_list_experiment_holdouts(self):
        response = self.client.get(f"/api/projects/{self.team.id}/experiment_holdouts/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_update_experiment_holdouts(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts/",
            data={
                "name": "Test Experiment holdout",
                "filters": [
                    {
                        "properties": [],
                        "rollout_percentage": 20,
                        "variant": "holdout",
                    }
                ],
            },
            format="json",
        )

        holdout_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment holdout")
        self.assertEqual(
            response.json()["filters"],
            [{"properties": [], "rollout_percentage": 20, "variant": f"holdout-{holdout_id}"}],
        )

        # Generate experiment to be part of holdout
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
                "holdout_id": holdout_id,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertEqual(
            created_ff.filters["holdout_groups"],
            [{"properties": [], "rollout_percentage": 20, "variant": f"holdout-{holdout_id}"}],
        )

        exp_id = response.json()["id"]
        # Now try updating holdout
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiment_holdouts/{holdout_id}",
            {
                "name": "Test Experiment holdout 2",
                "filters": [
                    {
                        "properties": [],
                        "rollout_percentage": 30,
                        "variant": "holdout",
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Test Experiment holdout 2")
        self.assertEqual(
            response.json()["filters"],
            [{"properties": [], "rollout_percentage": 30, "variant": f"holdout-{holdout_id}"}],
        )

        # make sure flag for experiment in question was updated as well
        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(
            created_ff.filters["holdout_groups"],
            [{"properties": [], "rollout_percentage": 30, "variant": f"holdout-{holdout_id}"}],
        )

        # now delete holdout
        response = self.client.delete(f"/api/projects/{self.team.id}/experiment_holdouts/{holdout_id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # make sure flag for experiment in question was updated as well
        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.filters["holdout_groups"], None)

        # and same for experiment
        exp = Experiment.objects.get(pk=exp_id)
        self.assertEqual(exp.holdout, None)

    def test_invalid_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts/",
            data={
                "name": None,  # invalid
                "filters": [
                    {
                        "properties": [],
                        "rollout_percentage": 20,
                        "variant": "holdout",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "This field may not be null.")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts/",
            data={
                "name": "xyz",
                "filters": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Filters are required to create an holdout group")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts",
            data={
                "name": "xyz",
                "filters": [
                    {
                        "properties": [],
                        "rollout_percentage": 150,
                        "variant": "holdout",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Rollout percentage must be between 0 and 100.")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts",
            data={
                "name": "xyz",
                "filters": [
                    {
                        "properties": [],
                        "rollout_percentage": -10,
                        "variant": "holdout",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Rollout percentage must be between 0 and 100.")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts",
            data={
                "name": "xyz",
                "filters": [
                    {
                        "properties": [],
                        "variant": "holdout",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Rollout percentage must be present.")
