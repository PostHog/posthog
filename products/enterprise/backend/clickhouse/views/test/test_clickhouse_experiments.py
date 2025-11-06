from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, FuzzyInt, _create_event, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from dateutil import parser
from rest_framework import status

from posthog.models import WebExperiment
from posthog.models.action.action import Action
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.cohort.cohort import Cohort
from posthog.models.experiment import Experiment, ExperimentSavedMetric
from posthog.models.feature_flag import FeatureFlag, get_feature_flags_for_team_in_cache
from posthog.models.user import User
from posthog.test.test_journeys import journeys_for

from products.enterprise.backend.api.test.base import APILicensedTest
from products.enterprise.backend.clickhouse.views.experiment_saved_metrics import ExperimentToSavedMetricSerializer


class TestExperimentCRUD(APILicensedTest):
    # List experiments
    def test_can_list_experiments(self):
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_getting_experiments_is_not_nplus1(self) -> None:
        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            data={
                "name": "Test Experiment",
                "feature_flag_key": f"flag_0",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
            format="json",
        ).json()

        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            data={
                "name": "Test Experiment",
                "feature_flag_key": f"exp_flag_000",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "end_date": "2021-12-01T10:23",
                "archived": True,
                "parameters": None,
            },
            format="json",
        ).json()

        with self.assertNumQueries(FuzzyInt(18, 19)):
            response = self.client.get(f"/api/projects/{self.team.id}/experiments")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        for i in range(1, 5):
            self.client.post(
                f"/api/projects/{self.team.id}/experiments/",
                data={
                    "name": "Test Experiment",
                    "feature_flag_key": f"flag_{i}",
                    "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                    "start_date": "2021-12-01T10:23",
                    "parameters": None,
                },
                format="json",
            ).json()

        with self.assertNumQueries(FuzzyInt(22, 23)):
            response = self.client.get(f"/api/projects/{self.team.id}/experiments")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_creating_updating_basic_experiment(self):
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
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)
        self.assertEqual(response.json()["stats_config"], {"method": "bayesian"})

        id = response.json()["id"]
        experiment = Experiment.objects.get(pk=id)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])

        end_date = "2021-12-10T00:00"

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "end_date": end_date},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")
        self.assertEqual(experiment.end_date.strftime("%Y-%m-%dT%H:%M"), end_date)

    def test_creating_experiment_with_ensure_experience_continuity(self):
        ff_key = "test-continuity-flag"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment with Continuity",
                "description": "",
                "start_date": None,  # Draft experiment
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {"ensure_experience_continuity": True},
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment with Continuity")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        # Check that the feature flag was created with ensure_experience_continuity
        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.ensure_experience_continuity, True)

        # Test with ensure_experience_continuity set to False
        ff_key_false = "test-no-continuity-flag"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment without Continuity",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key_false,
                "parameters": {"ensure_experience_continuity": False},
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_ff_false = FeatureFlag.objects.get(key=ff_key_false)
        self.assertEqual(created_ff_false.ensure_experience_continuity, False)

        # Test without specifying ensure_experience_continuity (should default to False)
        ff_key_default = "test-default-continuity-flag"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment with Default Continuity",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key_default,
                "parameters": {},
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_ff_default = FeatureFlag.objects.get(key=ff_key_default)
        self.assertEqual(created_ff_default.ensure_experience_continuity, False)

    def test_creating_updating_web_experiment(self):
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "type": "web",
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
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)
        web_experiment_id = response.json()["id"]
        self.assertEqual(
            WebExperiment.objects.get(pk=web_experiment_id).variants,
            {"test": {"rollout_percentage": 50}, "control": {"rollout_percentage": 50}},
        )

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])

        id = response.json()["id"]
        end_date = "2021-12-10T00:00"

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "end_date": end_date},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")
        self.assertEqual(experiment.end_date.strftime("%Y-%m-%dT%H:%M"), end_date)

    def test_transferring_holdout_to_another_group(self):
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

        # Generate draft experiment to be part of holdout
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
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
        self.assertEqual(
            created_ff.filters["holdout_groups"],
            [{"properties": [], "rollout_percentage": 20, "variant": f"holdout-{holdout_id}"}],
        )

        exp_id = response.json()["id"]

        # new holdout, and update experiment
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts/",
            data={
                "name": "Test Experiment holdout 2",
                "filters": [
                    {
                        "properties": [],
                        "rollout_percentage": 5,
                        "variant": "holdout",
                    }
                ],
            },
            format="json",
        )
        holdout_2_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"holdout_id": holdout_2_id},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=exp_id)
        self.assertEqual(experiment.holdout_id, holdout_2_id)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(
            created_ff.filters["holdout_groups"],
            [{"properties": [], "rollout_percentage": 5, "variant": f"holdout-{holdout_2_id}"}],
        )

        # update parameters
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
            },
        )

        experiment = Experiment.objects.get(pk=exp_id)
        self.assertEqual(experiment.holdout_id, holdout_2_id)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(
            created_ff.filters["holdout_groups"],
            [{"properties": [], "rollout_percentage": 5, "variant": f"holdout-{holdout_2_id}"}],
        )
        self.assertEqual(
            created_ff.filters["multivariate"]["variants"],
            [
                {"key": "control", "name": "Control Group", "rollout_percentage": 33},
                {"key": "test_1", "name": "Test Variant", "rollout_percentage": 33},
                {"key": "test_2", "name": "Test Variant", "rollout_percentage": 34},
            ],
        )

        # remove holdouts
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"holdout_id": None},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=exp_id)
        self.assertEqual(experiment.holdout_id, None)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.filters["holdout_groups"], None)

        # try adding invalid holdout
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"holdout_id": 123456},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], 'Invalid pk "123456" - object does not exist.')

        # add back holdout
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"holdout_id": holdout_2_id},
        )

        # launch experiment and try updating holdouts again
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"start_date": "2021-12-01T10:23"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"holdout_id": holdout_id},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Can't update holdout on running Experiment")

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(
            created_ff.filters["holdout_groups"],
            [{"properties": [], "rollout_percentage": 5, "variant": f"holdout-{holdout_2_id}"}],
        )

    def test_saved_metrics(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {
                        "kind": "TrendsQuery",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    },
                },
            },
        )

        saved_metric_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment saved metric")
        self.assertEqual(response.json()["description"], "Test description")
        self.assertEqual(
            response.json()["query"],
            {
                "kind": "ExperimentTrendsQuery",
                "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
            },
        )
        self.assertEqual(response.json()["created_by"]["id"], self.user.pk)

        # Generate experiment to have saved metric
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
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "secondary"}}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        exp_id = response.json()["id"]

        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 1)
        experiment_to_saved_metric = Experiment.objects.get(pk=exp_id).experimenttosavedmetric_set.first()
        self.assertEqual(experiment_to_saved_metric.metadata, {"type": "secondary"})
        saved_metric = Experiment.objects.get(pk=exp_id).saved_metrics.first()
        self.assertEqual(saved_metric.id, saved_metric_id)
        self.assertEqual(
            saved_metric.query,
            {
                "kind": "ExperimentTrendsQuery",
                "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
            },
        )

        # Now try updating experiment with new saved metric
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Test Experiment saved metric 2",
                "description": "Test description 2",
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageleave"}]},
                },
            },
        )

        saved_metric_2_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment saved metric 2")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {
                "saved_metrics_ids": [
                    {"id": saved_metric_id, "metadata": {"type": "secondary"}},
                    {"id": saved_metric_2_id, "metadata": {"type": "tertiary"}},
                ]
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 2)
        experiment_to_saved_metric = Experiment.objects.get(pk=exp_id).experimenttosavedmetric_set.all()
        self.assertEqual(experiment_to_saved_metric[0].metadata, {"type": "secondary"})
        self.assertEqual(experiment_to_saved_metric[1].metadata, {"type": "tertiary"})
        saved_metric = Experiment.objects.get(pk=exp_id).saved_metrics.all()
        self.assertEqual(sorted([saved_metric[0].id, saved_metric[1].id]), [saved_metric_id, saved_metric_2_id])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"saved_metrics_ids": []},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 0)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {
                "saved_metrics_ids": [
                    {"id": saved_metric_id, "metadata": {"type": "secondary"}},
                ]
            },
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"saved_metrics_ids": None},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 0)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {
                "saved_metrics_ids": [
                    {"id": saved_metric_id, "metadata": {"type": "secondary"}},
                ]
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 1)

        # not updating saved metrics shouldn't change anything
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {
                "name": "Test Experiment 2",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 1)

        # now delete saved metric
        response = self.client.delete(f"/api/projects/{self.team.id}/experiment_saved_metrics/{saved_metric_id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # make sure experiment in question was updated as well
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 0)

    def test_validate_saved_metrics_payload(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
                },
            },
        )

        saved_metric_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Generate experiment to have saved metric
        ff_key = "a-b-tests"
        exp_data = {
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
        }
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                **exp_data,
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"xxx": "secondary"}}],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(
            response.json()["detail"],
            "Metadata must have a type key",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                **exp_data,
                "saved_metrics_ids": [{"saved_metric": saved_metric_id}],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(response.json()["detail"], "Saved metric must have an id")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                **exp_data,
                "saved_metrics_ids": [{"id": 12345678}],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(response.json()["detail"], "Saved metric does not exist")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                **exp_data,
                "saved_metrics_ids": {"id": saved_metric_id},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(response.json()["detail"], 'Expected a list of items but got type "dict".')

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                **exp_data,
                "saved_metrics_ids": [[saved_metric_id]],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(response.json()["detail"], "Saved metric must be an object")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                **exp_data,
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": "secondary"}],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(response.json()["detail"], "Metadata must be an object")

    @freeze_time("2025-02-10T13:00:00Z")
    def test_fetching_experiment_with_stale_metric_dates_applies_experiment_date_range(self):
        test_feature_flag = FeatureFlag.objects.create(
            name=f"Test experiment flag",
            key="test-flag",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "test",
                            "name": "Test",
                            "rollout_percentage": 50,
                        },
                    ]
                },
            },
            created_by=self.user,
        )
        funnel_query = {
            "kind": "ExperimentFunnelsQuery",
            "funnels_query": {
                "kind": "FunnelsQuery",
                "series": [
                    {"kind": "EventsNode", "name": "[jan-16-running] seen", "event": "[jan-16-running] seen"},
                    {"kind": "EventsNode", "name": "[jan-16-running] payment", "event": "[jan-16-running] payment"},
                ],
                "dateRange": {"date_to": "2025-02-13T23:59", "date_from": "2025-01-30T12:16", "explicitDate": True},
                "funnelsFilter": {
                    "layout": "horizontal",
                    "funnelVizType": "steps",
                    "funnelWindowInterval": 14,
                    "funnelWindowIntervalUnit": "day",
                },
                "filterTestAccounts": True,
            },
        }
        trends_query = {
            "kind": "ExperimentTrendsQuery",
            "count_query": {
                "kind": "TrendsQuery",
                "series": [
                    {
                        "kind": "EventsNode",
                        "math": "total",
                        "name": "[jan-16-running] event one",
                        "event": "[jan-16-running] event one",
                    }
                ],
                "interval": "day",
                "dateRange": {"date_to": "2025-01-16T23:59", "date_from": "2025-01-02T13:54", "explicitDate": True},
                "trendsFilter": {"display": "ActionsLineGraph"},
                "filterTestAccounts": True,
            },
        }
        saved_trends_metric = ExperimentSavedMetric.objects.create(
            name="Test saved metric",
            description="Test description",
            query=trends_query,
            team=self.team,
            created_by=self.user,
        )
        saved_funnel_metric = ExperimentSavedMetric.objects.create(
            name="Test saved metric",
            description="Test description",
            query=funnel_query,
            team=self.team,
            created_by=self.user,
        )
        experiment = Experiment.objects.create(
            name="Test Experiment with stale dates",
            team=self.team,
            feature_flag=test_feature_flag,
            start_date=datetime(2025, 2, 1),
            end_date=None,
            metrics=[funnel_query],
            metrics_secondary=[trends_query],
        )

        for saved_metric_data in [saved_funnel_metric, saved_trends_metric]:
            saved_metric_serializer = ExperimentToSavedMetricSerializer(
                data={
                    "experiment": experiment.id,
                    "saved_metric": saved_metric_data.id,
                    "metadata": {"type": "secondary"},
                },
            )
            saved_metric_serializer.is_valid(raise_exception=True)
            saved_metric_serializer.save()

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["metrics"][0]["funnels_query"]["dateRange"]["date_from"], "2025-02-01T00:00:00Z"
        )
        self.assertEqual(response.json()["metrics"][0]["funnels_query"]["dateRange"]["date_to"], "")
        self.assertEqual(
            response.json()["metrics_secondary"][0]["count_query"]["dateRange"]["date_from"], "2025-02-01T00:00:00Z"
        )
        self.assertEqual(response.json()["metrics_secondary"][0]["count_query"]["dateRange"]["date_to"], "")
        self.assertEqual(
            response.json()["saved_metrics"][0]["query"]["funnels_query"]["dateRange"]["date_from"],
            "2025-02-01T00:00:00Z",
        )
        self.assertEqual(response.json()["saved_metrics"][0]["query"]["funnels_query"]["dateRange"]["date_to"], "")
        self.assertEqual(
            response.json()["saved_metrics"][1]["query"]["count_query"]["dateRange"]["date_from"],
            "2025-02-01T00:00:00Z",
        )
        self.assertEqual(response.json()["saved_metrics"][1]["query"]["count_query"]["dateRange"]["date_to"], "")

    def test_adding_behavioral_cohort_filter_to_experiment_fails(self):
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 2,
                            "time_interval": "week",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        },
                    ],
                }
            },
            name="cohort_behavioral",
        )
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
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        id = response.json()["id"]

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"filters": {"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(
            response.json()["detail"],
            "Experiments do not support global filter properties",
        )

    def test_invalid_create(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": None,  # invalid
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "This field may not be null.")

    def test_experiment_date_validation(self):
        ff_key = "a-b-tests"

        # Test 1: End date same as start date
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2024-02-10T00:00:00Z",
                "end_date": "2024-02-10T00:00:00Z",
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "End date must be after start date")

        # Test 2: End date before start date
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2024-02-10T00:00:00Z",
                "end_date": "2024-02-09T00:00:00Z",
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "End date must be after start date")

        # Test 3: Valid dates
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2024-02-10T00:00:00Z",
                "end_date": "2024-02-11T00:00:00Z",
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["start_date"], "2024-02-10T00:00:00Z")
        self.assertEqual(response.json()["end_date"], "2024-02-11T00:00:00Z")

        # Test 4: Update with invalid dates
        experiment_id = response.json()["id"]
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {
                "start_date": "2024-02-15T00:00:00Z",
                "end_date": "2024-02-14T00:00:00Z",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "End date must be after start date")

        # Test 5: Only start date provided (should be valid)
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2024-02-10T00:00:00Z",
                "end_date": None,
                "feature_flag_key": ff_key + "_2",
                "parameters": {},
                "filters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["start_date"], "2024-02-10T00:00:00Z")
        self.assertIsNone(response.json()["end_date"])

        # Test 6: Only end date provided (should be valid)
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": "2024-02-11T00:00:00Z",
                "feature_flag_key": ff_key + "_3",
                "parameters": {},
                "filters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.json()["start_date"])
        self.assertEqual(response.json()["end_date"], "2024-02-11T00:00:00Z")

    def test_invalid_update(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        id = response.json()["id"]

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {},
                "feature_flag_key": "new_key",
            },  # invalid
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Can't update keys: get_feature_flag_key on Experiment",
        )

    def test_draft_experiment_doesnt_have_FF_active(self):
        # Draft experiment
        ff_key = "a-b-tests"
        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)

    def test_draft_experiment_doesnt_have_FF_active_even_after_updates(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        id = response.json()["id"]

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [{"id": "$pageview"}],
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)  # didn't change to enabled while still draft

        # Now launch experiment
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"start_date": "2021-12-01T10:23"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertTrue(created_ff.active)

    def test_launching_draft_experiment_activates_FF(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": [{"id": "$pageview"}]},
            },
        )

        id = response.json()["id"]
        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "start_date": "2021-12-01T10:23"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        updated_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertTrue(updated_ff.active)

    def test_draft_experiment_update_doesnt_delete_ff_payloads(self):
        # Draft experiment
        ff_key = "a-b-tests-with-flag-payloads"
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )
        id = create_response.json()["id"]

        created_ff = FeatureFlag.objects.get(key=ff_key)
        # Update feature flag payloads
        created_ff.filters["payloads"] = {"test": '"test-payload"', "control": '"control-payload"'}
        created_ff.save()

        # Update parameters on experiment
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Update parameters",
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "special",
                            "name": "Special Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
            },
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        updated_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(updated_ff.filters["payloads"], {"test": '"test-payload"', "control": '"control-payload"'})

    def test_create_multivariate_experiment_can_update_variants_in_draft(self):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.active, False)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test_1")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][2]["key"], "test_2")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])

        id = response.json()["id"]

        experiment = Experiment.objects.get(id=response.json()["id"])
        self.assertTrue(experiment.is_draft)
        # Now try updating FF
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 24,
                        },
                        {
                            "key": "test_3",
                            "name": "Test Variant",
                            "rollout_percentage": 10,
                        },
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.active, False)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][3]["key"], "test_3")

    def test_create_multivariate_experiment(self):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.active, True)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test_1")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][2]["key"], "test_2")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])

        id = response.json()["id"]

        experiment = Experiment.objects.get(id=response.json()["id"])
        self.assertFalse(experiment.is_draft)
        # Now try updating FF
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {"feature_flag_variants": [{"key": "control", "name": "X", "rollout_percentage": 33}]},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Can't update feature_flag_variants on Experiment",
        )

        # Allow changing FF rollout %s
        created_ff = FeatureFlag.objects.get(key=ff_key)
        created_ff.filters = {
            **created_ff.filters,
            "multivariate": {
                "variants": [
                    {
                        "key": "control",
                        "name": "Control Group",
                        "rollout_percentage": 35,
                    },
                    {"key": "test_1", "name": "Test Variant", "rollout_percentage": 33},
                    {"key": "test_2", "name": "Test Variant", "rollout_percentage": 32},
                ]
            },
        }
        created_ff.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga 222",
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["parameters"]["feature_flag_variants"][0]["key"], "control")
        self.assertEqual(response.json()["description"], "Bazinga 222")
        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.active, True)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["rollout_percentage"], 35)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test_1")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["rollout_percentage"], 33)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][2]["key"], "test_2")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][2]["rollout_percentage"], 32)

        # Now try changing FF keys
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Can't update feature_flag_variants on Experiment",
        )

        # Now try updating other parameter keys
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "parameters": {"recommended_sample_size": 1500}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["parameters"]["recommended_sample_size"], 1500)

    def test_creating_invalid_multivariate_experiment_no_control(self):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        # no control
                        {
                            "key": "test_0",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Feature flag variants must contain a control variant",
        )

    def test_creating_updating_experiment_with_group_aggregation(self):
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                    "aggregation_group_type_index": 1,
                },
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
        self.assertTrue(created_ff.filters["aggregation_group_type_index"] is None)

        id = response.json()["id"]

        # Now update group type index on filter
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                    "aggregation_group_type_index": 0,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertTrue(created_ff.filters["aggregation_group_type_index"] is None)

        # Now remove group type index
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                    # "aggregation_group_type_index": None, # removed key
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertTrue(created_ff.filters["aggregation_group_type_index"] is None)

    def test_creating_experiment_with_group_aggregation_parameter(self):
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "aggregation_group_type_index": 0,
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
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
        self.assertEqual(created_ff.filters["aggregation_group_type_index"], 0)

        id = response.json()["id"]

        # Now update group type index on filter
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                    "aggregation_group_type_index": 1,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertEqual(created_ff.filters["aggregation_group_type_index"], 0)

    def test_used_in_experiment_is_populated_correctly_for_feature_flag_list(self) -> None:
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_experiment = response.json()["id"]

        # add another random feature flag
        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": f"flag",
                "key": f"flag_0",
                "filters": {"groups": [{"rollout_percentage": 5}]},
            },
            format="json",
        ).json()

        # TODO: Make sure permission bool doesn't cause n + 1
        with self.assertNumQueries(22):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            result = response.json()

            self.assertEqual(result["count"], 2)

            self.assertCountEqual(
                [(res["key"], res["experiment_set"]) for res in result["results"]],
                [("flag_0", []), (ff_key, [created_experiment])],
            )

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_create_experiment_updates_feature_flag_cache(self, mock_on_commit):
        cache.clear()

        initial_cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        self.assertIsNone(initial_cached_flags)

        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        # save was called, but no flags saved because experiment is in draft mode, so flag is not active
        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(0, len(cached_flags))

        id = response.json()["id"]

        # launch experiment
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "start_date": "2021-12-01T10:23",
            },
        )

        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(1, len(cached_flags))
        self.assertEqual(cached_flags[0].key, ff_key)
        self.assertEqual(
            cached_flags[0].filters,
            {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "aggregation_group_type_index": None,
                "holdout_groups": None,
            },
        )

        # Now try updating FF
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {"feature_flag_variants": [{"key": "control", "name": "X", "rollout_percentage": 33}]},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Can't update feature_flag_variants on Experiment",
        )

        # ensure cache doesn't change either
        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(1, len(cached_flags))
        self.assertEqual(cached_flags[0].key, ff_key)
        self.assertEqual(
            cached_flags[0].filters,
            {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "aggregation_group_type_index": None,
                "holdout_groups": None,
            },
        )

        # Now try changing FF rollout %s
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 34,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 32,
                        },
                    ]
                },
            },
        )
        # changing variants isn't really supported by experiments anymore, need to do it directly
        # on the FF
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # ensure cache doesn't change either
        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(1, len(cached_flags))
        self.assertEqual(cached_flags[0].key, ff_key)
        self.assertEqual(
            cached_flags[0].filters,
            {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "aggregation_group_type_index": None,
                "holdout_groups": None,
            },
        )

    def test_create_draft_experiment_with_filters(self) -> None:
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
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
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

    def test_create_launched_experiment_with_filters(self) -> None:
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
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

    def test_create_draft_experiment_without_filters(self) -> None:
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

    def test_create_experiment_with_feature_flag_missing_control(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Beta feature",
            key="beta-feature",
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "test-1", "rollout_percentage": 50},
                        {"key": "test-2", "rollout_percentage": 50},
                    ]
                }
            },
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Beta experiment",
                "feature_flag_key": feature_flag.key,
                "parameters": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Feature flag must have control as the first variant.")

    def test_create_experiment_with_valid_existing_feature_flag(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Beta feature",
            key="beta-feature",
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                }
            },
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Beta experiment",
                "feature_flag_key": feature_flag.key,
                "parameters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["feature_flag"]["id"], feature_flag.id)

    def test_create_multiple_experiments_with_same_feature_flag(self):
        # Create a feature flag with proper structure for experiments
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Shared feature flag",
            key="shared-feature-flag",
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                }
            },
            created_by=self.user,
        )

        # Create first experiment with this feature flag
        first_experiment_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "First experiment",
                "feature_flag_key": feature_flag.key,
                "parameters": {},
            },
        )

        self.assertEqual(first_experiment_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first_experiment_response.json()["feature_flag"]["id"], feature_flag.id)

        # Create second experiment with the same feature flag - this would have previously failed
        second_experiment_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Second experiment",
                "feature_flag_key": feature_flag.key,
                "parameters": {},
            },
        )

        # Assert that the second experiment is created successfully
        self.assertEqual(second_experiment_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_experiment_response.json()["feature_flag"]["id"], feature_flag.id)

        # Verify both experiments exist and point to the same feature flag
        first_experiment_id = first_experiment_response.json()["id"]
        second_experiment_id = second_experiment_response.json()["id"]

        # Ensure both experiments exist in the database
        first_experiment = Experiment.objects.get(id=first_experiment_id)
        second_experiment = Experiment.objects.get(id=second_experiment_id)

        # Verify both experiments use the same feature flag
        self.assertEqual(first_experiment.feature_flag_id, feature_flag.id)
        self.assertEqual(second_experiment.feature_flag_id, feature_flag.id)

    def test_feature_flag_and_experiment_sync(self):
        # Create an experiment with control and test variants
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "My test experiment",
                "feature_flag_key": "experiment-test-flag",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                        {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                    ]
                },
                "filters": {"insight": "TRENDS", "events": [{"order": 0, "id": "$pageview"}]},
            },
        )

        self.assertEqual(response.status_code, 201)
        experiment_id = response.json()["id"]
        feature_flag_id = response.json()["feature_flag"]["id"]

        # Fetch the FeatureFlag object
        feature_flag = FeatureFlag.objects.get(id=feature_flag_id)

        variants = feature_flag.filters["multivariate"]["variants"]

        # Verify that the variants are correctly populated
        self.assertEqual(len(variants), 2)

        self.assertEqual(variants[0]["key"], "control")
        self.assertEqual(variants[0]["name"], "Control Group")
        self.assertEqual(variants[0]["rollout_percentage"], 50)

        self.assertEqual(variants[1]["key"], "test")
        self.assertEqual(variants[1]["name"], "Test Variant")
        self.assertEqual(variants[1]["rollout_percentage"], 50)

        # Change the rollout percentages and groups of the feature flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag_id}",
            {
                "filters": {
                    "groups": [
                        {"properties": [], "rollout_percentage": 99},
                        {"properties": [], "rollout_percentage": 1},
                    ],
                    "payloads": {},
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 10},
                            {"key": "test", "rollout_percentage": 90},
                        ]
                    },
                    "aggregation_group_type_index": 1,
                }
            },
        )

        # Verify that Experiment.parameters.feature_flag_variants reflects the updated FeatureFlag.filters.multivariate.variants
        experiment = Experiment.objects.get(id=experiment_id)
        self.assertEqual(
            experiment.parameters["feature_flag_variants"],
            [{"key": "control", "rollout_percentage": 10}, {"key": "test", "rollout_percentage": 90}],
        )
        self.assertEqual(experiment.parameters["aggregation_group_type_index"], 1)

        # Update the experiment with an unrelated change
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"name": "Updated Test Experiment"},
        )

        # Verify that the feature flag variants and groups remain unchanged
        feature_flag = FeatureFlag.objects.get(id=feature_flag_id)
        self.assertEqual(
            feature_flag.filters["multivariate"]["variants"],
            [{"key": "control", "rollout_percentage": 10}, {"key": "test", "rollout_percentage": 90}],
        )
        self.assertEqual(
            feature_flag.filters["groups"],
            [{"properties": [], "rollout_percentage": 99}, {"properties": [], "rollout_percentage": 1}],
        )

        # Test removing aggregation_group_type_index
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag_id}",
            {
                "filters": {
                    "groups": [
                        {"properties": [], "rollout_percentage": 99},
                        {"properties": [], "rollout_percentage": 1},
                    ],
                    "payloads": {},
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 10},
                            {"key": "test", "rollout_percentage": 90},
                        ]
                    },
                }
            },
        )

        # Verify that aggregation_group_type_index is removed from experiment parameters
        experiment = Experiment.objects.get(id=experiment_id)
        self.assertNotIn("aggregation_group_type_index", experiment.parameters)

    def test_update_experiment_exposure_config_valid(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Test Feature Flag",
            key="test-feature-flag",
            filters={},
        )

        experiment = Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            description="My test experiment",
            feature_flag=feature_flag,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment.id}",
            {
                "exposure_criteria": {
                    "filterTestAccounts": True,
                    "exposure_config": {
                        "event": "$pageview",
                        "properties": [
                            {"key": "plan", "operator": "is_not", "value": "free", "type": "event"},
                        ],
                    },
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(id=experiment.id)
        self.assertEqual(experiment.exposure_criteria["filterTestAccounts"], True)
        self.assertEqual(experiment.exposure_criteria["exposure_config"]["event"], "$pageview")
        self.assertEqual(
            experiment.exposure_criteria["exposure_config"]["properties"],
            [{"key": "plan", "operator": "is_not", "value": "free", "type": "event"}],
        )

    def test_update_experiment_exposure_config_invalid(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Test Feature Flag",
            key="test-feature-flag",
            filters={},
        )

        experiment = Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            description="My test experiment",
            feature_flag=feature_flag,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment.id}",
            {
                "exposure_criteria": {
                    "filterTestAccounts": True,
                    "exposure_config": {
                        # Invalid event and properties
                        "event": "",
                        "properties": [
                            1,
                        ],
                    },
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_experiment_exposure_config_with_action(self):
        # Create an action
        action = Action.objects.create(
            name="Test Action",
            team=self.team,
            steps_json=[{"event": "purchase", "properties": [{"key": "plan", "value": "premium", "type": "event"}]}],
        )

        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Test Feature Flag",
            key="test-feature-flag",
            filters={},
        )
        experiment = Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            description="My test experiment",
            feature_flag=feature_flag,
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment.id}",
            {
                "exposure_criteria": {
                    "filterTestAccounts": False,
                    "exposure_config": {
                        "kind": "ActionsNode",
                        "id": action.id,
                    },
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        experiment = Experiment.objects.get(id=experiment.id)
        assert experiment.exposure_criteria is not None
        self.assertEqual(experiment.exposure_criteria["filterTestAccounts"], False)
        self.assertEqual(experiment.exposure_criteria["exposure_config"]["kind"], "ActionsNode")
        self.assertEqual(experiment.exposure_criteria["exposure_config"]["id"], action.id)

    def test_create_experiment_in_specific_folder(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Folder Test Experiment",
                "description": "This experiment goes in a custom folder",
                "feature_flag_key": "folder-experiment",
                # ensure the experiment is in draft so it doesn't fail if user doesn't pass certain date fields
                "start_date": None,
                "filters": {"events": [], "properties": []},
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
                "_create_in_folder": "Special Folder/Experiments",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        experiment_id = response.json()["id"]
        self.assertTrue(Experiment.objects.filter(id=experiment_id).exists())

        ff_key = response.json()["feature_flag_key"]
        self.assertTrue(FeatureFlag.objects.filter(team=self.team, key=ff_key).exists())
        ff_id = FeatureFlag.objects.filter(team=self.team, key=ff_key).first().id

        from posthog.models.file_system.file_system import FileSystem

        fs_entry = FileSystem.objects.filter(team=self.team, ref=str(experiment_id), type="experiment").first()
        assert fs_entry is not None, "Expected a FileSystem entry for the newly created experiment."
        assert (
            "Special Folder/Experiments" in fs_entry.path
        ), f"Expected path to contain 'Special Folder/Experiments', got {fs_entry.path}"

        ff_entry = FileSystem.objects.filter(team=self.team, ref=str(ff_id), type="feature_flag").first()
        assert ff_entry is not None, "Expected a FileSystem entry for the newly created feature flag."
        assert (
            "Special Folder/Experiments" in ff_entry.path
        ), f"Expected path to contain 'Special Folder/Experiments', got {ff_entry.path}"

    def test_list_endpoint_excludes_deleted_experiments(self):
        """Test that list endpoint doesn't return soft-deleted experiments"""

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-flag",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
            format="json",
        )
        experiment_id = response.json()["id"]

        response2 = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Active Experiment",
                "feature_flag_key": "active-flag",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
            format="json",
        )
        active_experiment_id = response2.json()["id"]

        # Soft delete the first experiment
        self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {"deleted": True},
            format="json",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/")
        experiment_ids = [exp["id"] for exp in response.json()["results"]]

        # Should only contain the active experiment
        self.assertIn(active_experiment_id, experiment_ids)
        self.assertNotIn(experiment_id, experiment_ids)

    def test_detail_endpoint_returns_404_for_deleted_experiment(self):
        """Test that detail endpoint returns 404 for soft-deleted experiments"""

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-flag",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
            format="json",
        )
        experiment_id = response.json()["id"]

        # Soft delete the experiment
        self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {"deleted": True},
            format="json",
        )

        # Try to get the deleted experiment
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_experiment_with_missing_parameters(self):
        ff_key = "a-b-tests"

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": ff_key,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_duplicate_experiment(self) -> None:
        """Test that experiments can be duplicated with the same settings and metrics"""
        ff_key = "duplicate-test-flag"

        # Create original experiment
        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Original Experiment",
                "description": "Original description",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                        {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                    ]
                },
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "metrics": [{"metric_type": "count", "count_query": {"events": [{"id": "$pageview"}]}}],
                "metrics_secondary": [{"metric_type": "count", "count_query": {"events": [{"id": "$click"}]}}],
                "stats_config": {"method": "bayesian"},
                "exposure_criteria": {"filterTestAccounts": True},
            },
        )

        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        # Duplicate the experiment
        duplicate_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/duplicate/",
            {},
        )

        self.assertEqual(duplicate_response.status_code, status.HTTP_201_CREATED)
        duplicate_experiment = duplicate_response.json()

        # Verify duplicate has correct properties
        self.assertEqual(duplicate_experiment["name"], "Original Experiment (Copy)")
        self.assertEqual(duplicate_experiment["description"], original_experiment["description"])
        self.assertEqual(duplicate_experiment["type"], original_experiment["type"])
        self.assertEqual(duplicate_experiment["parameters"], original_experiment["parameters"])
        self.assertEqual(duplicate_experiment["filters"], original_experiment["filters"])

        # Compare metrics ignoring fingerprints (they differ due to different start_dates)
        def remove_fingerprints(metrics):
            return [{k: v for k, v in metric.items() if k != "fingerprint"} for metric in metrics or []]

        self.assertEqual(
            remove_fingerprints(duplicate_experiment["metrics"]), remove_fingerprints(original_experiment["metrics"])
        )
        self.assertEqual(
            remove_fingerprints(duplicate_experiment["metrics_secondary"]),
            remove_fingerprints(original_experiment["metrics_secondary"]),
        )
        self.assertEqual(duplicate_experiment["stats_config"], original_experiment["stats_config"])
        self.assertEqual(duplicate_experiment["exposure_criteria"], original_experiment["exposure_criteria"])

        # Verify feature flag is reused
        self.assertEqual(duplicate_experiment["feature_flag_key"], original_experiment["feature_flag_key"])

        # Verify reset fields
        self.assertIsNone(duplicate_experiment["start_date"])
        self.assertIsNone(duplicate_experiment["end_date"])
        self.assertFalse(duplicate_experiment["archived"])
        self.assertFalse(duplicate_experiment["deleted"])

        # Verify different IDs
        self.assertNotEqual(duplicate_experiment["id"], original_experiment["id"])

    def test_duplicate_experiment_name_conflict_resolution(self) -> None:
        """Test that duplicate experiment names are handled with incremental suffixes"""
        ff_key = "name-conflict-test-flag"

        # Create original experiment
        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Conflict Test",
                "feature_flag_key": ff_key,
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
            },
        )

        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        # Create first duplicate
        first_duplicate_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/duplicate/",
            {},
        )

        self.assertEqual(first_duplicate_response.status_code, status.HTTP_201_CREATED)
        first_duplicate = first_duplicate_response.json()
        self.assertEqual(first_duplicate["name"], "Conflict Test (Copy)")

        # Create second duplicate to test name conflict resolution
        second_duplicate_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/duplicate/",
            {},
        )

        self.assertEqual(second_duplicate_response.status_code, status.HTTP_201_CREATED)
        second_duplicate = second_duplicate_response.json()
        self.assertEqual(second_duplicate["name"], "Conflict Test (Copy) 1")

    def test_duplicate_experiment_with_custom_feature_flag(self) -> None:
        """Test that experiments can be duplicated with a different feature flag"""
        # Create original experiment
        original_ff_key = "original-flag"
        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Original Experiment",
                "description": "Original description",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": original_ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                        {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                    ]
                },
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "metrics": [{"metric_type": "count", "count_query": {"events": [{"id": "$pageview"}]}}],
                "metrics_secondary": [{"metric_type": "count", "count_query": {"events": [{"id": "$click"}]}}],
            },
        )

        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        # Create a new feature flag to use for the duplicate
        new_flag = FeatureFlag.objects.create(
            team=self.team,
            key="duplicate-test-flag",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        # Duplicate the experiment with a custom feature flag
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/duplicate",
            {"feature_flag_key": new_flag.key},
        )

        assert response.status_code == 201
        duplicate_data = response.json()

        # Verify the duplicate uses the new feature flag
        assert duplicate_data["feature_flag_key"] == "duplicate-test-flag"
        assert duplicate_data["feature_flag"]["key"] == "duplicate-test-flag"

        # Verify the duplicate has the same settings
        assert duplicate_data["description"] == original_experiment["description"]
        assert duplicate_data["parameters"] == original_experiment["parameters"]
        assert duplicate_data["filters"] == original_experiment["filters"]

        # Compare metrics ignoring fingerprints (they differ due to different start_dates)
        def remove_fingerprints(metrics):
            return [{k: v for k, v in metric.items() if k != "fingerprint"} for metric in metrics or []]

        assert remove_fingerprints(duplicate_data["metrics"]) == remove_fingerprints(original_experiment["metrics"])
        assert remove_fingerprints(duplicate_data["metrics_secondary"]) == remove_fingerprints(
            original_experiment["metrics_secondary"]
        )

        # Verify temporal fields are reset
        assert duplicate_data["start_date"] is None
        assert duplicate_data["end_date"] is None
        assert duplicate_data["archived"] is False

    def test_metric_fingerprinting(self):
        """Test that metric fingerprints are computed correctly on create and update"""

        # Step 1: Create experiment with 3 metrics (tests create method fingerprinting)
        ff_key = "fingerprint-test"

        initial_mean_metric = {
            "uuid": "metric-1",
            "name": "Initial Mean Metric",
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {
                "kind": "EventsNode",
                "event": "$session_duration",
            },
        }

        initial_funnel_metric = {
            "uuid": "metric-2",
            "name": "Initial Funnel Metric",
            "kind": "ExperimentMetric",
            "metric_type": "funnel",
            "series": [
                {"kind": "EventsNode", "event": "$pageview"},
                {"kind": "EventsNode", "event": "$autocapture"},
            ],
        }

        initial_ratio_metric = {
            "uuid": "metric-3",
            "name": "Initial Ratio Metric",
            "kind": "ExperimentMetric",
            "metric_type": "ratio",
            "numerator": {"kind": "EventsNode", "event": "$session_duration"},
            "denominator": {"kind": "EventsNode", "event": "$autocapture"},
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Fingerprint Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},
                "metrics": [initial_mean_metric, initial_funnel_metric, initial_ratio_metric],
            },
        )
        exp_id = response.json()["id"]
        initial_metrics = response.json()["metrics"]

        expected_initial_fingerprints = {
            "mean": "1a5694c7330b8fb9f920fa6f1e6d871cc07e55e9d87447cb01a3384ed732c605",
            "funnel": "bf2d01d67d7a1f608177b6f3a9971a6c263870d23ad5935054b5069286575a94",
            "ratio": "3332b31c0ec0c8be353d5ed1f5740758affc9136d9721dba60434cbe104adb95",
        }

        for metric in initial_metrics:
            metric_type = metric["metric_type"]
            self.assertEqual(metric["fingerprint"], expected_initial_fingerprints[metric_type])

        # Step 2: Update with different metrics, conversion windows, start_date, stats_config, exposure_criteria
        updated_funnel_metric = {
            "goal": "increase",
            "kind": "ExperimentMetric",
            "uuid": "964398d7-ec8a-424d-890b-4e6bbc9a5c84",
            "series": [{"kind": "EventsNode", "name": "$pageview", "event": "$pageview"}],
            "metric_type": "funnel",
            "conversion_window": 14,
            "conversion_window_unit": "day",
            "funnel_order_type": "unordered",
        }

        updated_mean_metric = {
            "goal": "increase",
            "kind": "ExperimentMetric",
            "uuid": "824e38ae-f9d7-41f4-962c-74c9e744529a",
            "source": {"kind": "EventsNode", "name": "$pageview", "event": "$pageview"},
            "metric_type": "mean",
            "conversion_window": 14,
            "conversion_window_unit": "day",
            "lower_bound_percentile": 0.05,
            "upper_bound_percentile": 0.95,
        }

        updated_ratio_metric = {
            "goal": "decrease",
            "kind": "ExperimentMetric",
            "uuid": "70e0c887-1f32-4c7d-8405-0faded2e9722",
            "numerator": {"kind": "EventsNode", "name": "$pageview", "event": "$pageview"},
            "denominator": {"kind": "EventsNode", "math": "total", "name": "$pageview", "event": "$pageview"},
            "metric_type": "ratio",
            "conversion_window": 14,
            "conversion_window_unit": "day",
        }

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {
                "metrics": [updated_funnel_metric, updated_mean_metric, updated_ratio_metric],
                "start_date": "2024-01-01T10:00:00Z",
                "stats_config": {"method": "frequentist"},
                "exposure_criteria": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "$feature_flag_called",
                    "properties": [],
                },
            },
        )

        updated_metrics = response.json()["metrics"]

        expected_updated_fingerprints = {
            "mean": "d6a393e5456b71c16961c45e07eb17cb86e4f7972549033f9883c99430248c02",
            "funnel": "9f7888cb2f7f9c3dac2b6482a964eef6911f97e376ed53305ed6653f7f70ce9b",
            "ratio": "1b83a833a62ff9c2f01ba86be1f3e578b97749d3264e08ff9e76d863865e3ff3",
        }

        for metric in updated_metrics:
            metric_type = metric["metric_type"]
            self.assertEqual(metric["fingerprint"], expected_updated_fingerprints[metric_type])


class TestExperimentAuxiliaryEndpoints(ClickhouseTestMixin, APILicensedTest):
    def _generate_experiment(self, start_date="2024-01-01T10:23", extra_parameters=None):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": start_date,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ],
                    **(extra_parameters or {}),
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)
        return response

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_create_exposure_cohort_for_experiment(self, patch_on_commit: MagicMock):
        response = self._generate_experiment("2024-01-01T10:23")

        created_experiment = response.json()["id"]

        journeys_for(
            {
                "person1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                ],
                "person2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "test_1"},
                    },
                ],
                "personX": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {"$feature_flag": "a-b-test2", "$feature_flag_response": "test_1"},
                    },
                ],
                # out of time range
                "person3": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2023-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                ],
                # wrong event
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2024-01-03"},
                    {"event": "$pageleave", "timestamp": "2024-01-05"},
                ],
                # doesn't have feature value set
                "person_out_of_end_date": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
            },
            self.team,
        )
        flush_persons_and_events()

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        cohort = response.json()["cohort"]
        self.assertEqual(cohort["name"], 'Users exposed to experiment "Test Experiment"')
        self.assertEqual(cohort["experiment_set"], [created_experiment])

        cohort_id = cohort["id"]

        while cohort["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")
            cohort = response.json()

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/persons/?cohort={cohort_id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(["person1", "person2"], sorted([res["name"] for res in response.json()["results"]]))

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_create_exposure_cohort_for_experiment_with_custom_event_exposure(self, patch_on_commit: MagicMock):
        self.maxDiff = None

        cohort_extra = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "value": "http://example.com",
                            "type": "person",
                            "operator": "exact",
                        },
                    ],
                }
            },
            name="cohort_X",
        )
        response = self._generate_experiment(
            "2024-01-01T10:23",
            {
                "custom_exposure_filter": {
                    "events": [
                        {
                            "id": "custom_exposure_event",
                            "order": 0,
                            "entity_type": "events",
                            "properties": [
                                {"key": "bonk", "value": "bonk"},
                                {"key": "id", "value": cohort_extra.id, "type": "cohort"},
                                {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
                                {"key": "bonk-person", "value": "bonk", "type": "person"},
                            ],
                        }
                    ],
                    "filter_test_accounts": False,
                }
            },
        )

        created_experiment = response.json()["id"]

        journeys_for(
            {
                "person1": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2024-01-02",
                        "properties": {"$current_url": "x", "bonk": "bonk"},
                    },
                ],
                "person2": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2024-01-02",
                        "properties": {"$current_url": "y", "bonk": "bonk"},
                    },
                ],
                "person2-no-bonk": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2024-01-02",
                        "properties": {"$current_url": "y"},
                    },
                ],
                "person2-not-in-prop": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2024-01-02",
                        "properties": {"$current_url": "yxxxx"},
                    },
                ],
                "personX": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {"$feature_flag": "a-b-test2", "$feature_flag_response": "test_1"},
                    },
                ],
                # out of time range
                "person3": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2023-01-02",
                        "properties": {"$current_url": "y"},
                    },
                ],
                # wrong event
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2024-01-03"},
                    {"event": "$pageleave", "timestamp": "2024-01-05"},
                ],
            },
            self.team,
        )
        flush_persons_and_events()

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        cohort = response.json()["cohort"]
        self.assertEqual(cohort["name"], 'Users exposed to experiment "Test Experiment"')
        self.assertEqual(cohort["experiment_set"], [created_experiment])
        self.assertEqual(
            cohort["filters"],
            {
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "bytecode": [
                                        "_H",
                                        1,
                                        32,
                                        "custom_exposure_event",
                                        32,
                                        "event",
                                        1,
                                        1,
                                        11,
                                        32,
                                        "bonk",
                                        32,
                                        "bonk",
                                        32,
                                        "properties",
                                        1,
                                        2,
                                        11,
                                        32,
                                        "x",
                                        32,
                                        "y",
                                        44,
                                        2,
                                        32,
                                        "$current_url",
                                        32,
                                        "properties",
                                        1,
                                        2,
                                        21,
                                        3,
                                        2,
                                        3,
                                        2,
                                    ],
                                    "conditionHash": "605645c960b2c67c",
                                    "event_filters": [
                                        {"key": "bonk", "type": "event", "value": "bonk"},
                                        {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
                                    ],
                                    "event_type": "events",
                                    "explicit_datetime": "2024-01-01T10:23:00+00:00",
                                    "key": "custom_exposure_event",
                                    "negation": False,
                                    "type": "behavioral",
                                    "value": "performed_event",
                                }
                            ],
                        }
                    ],
                }
            },
        )

        cohort_id = cohort["id"]

        while cohort["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")
            cohort = response.json()

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/persons/?cohort={cohort_id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(["person1", "person2"], sorted([res["name"] for res in response.json()["results"]]))

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_create_exposure_cohort_for_experiment_with_custom_action_filters_exposure(
        self, patch_on_commit: MagicMock
    ):
        cohort_extra = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "value": "http://example.com",
                            "type": "person",
                            "operator": "exact",
                        },
                    ],
                }
            },
            name="cohort_X",
        )

        action1 = Action.objects.create(
            team=self.team,
            name="action1",
            steps_json=[
                {
                    "event": "insight viewed",
                    "properties": [
                        {
                            "key": "insight",
                            "type": "event",
                            "value": ["RETENTION"],
                            "operator": "exact",
                        },
                        {
                            "key": "id",
                            "value": cohort_extra.id,
                            "type": "cohort",
                        },
                    ],
                },
                {
                    "event": "insight viewed",
                    "properties": [
                        {
                            "key": "filters_count",
                            "type": "event",
                            "value": "1",
                            "operator": "gt",
                        }
                    ],
                },
                {
                    "event": "$autocapture",
                    "url": "/123",
                    "url_matching": "regex",
                },
            ],
        )
        response = self._generate_experiment(
            datetime.now() - timedelta(days=5),
            {
                "custom_exposure_filter": {
                    "actions": [
                        {
                            "id": str(action1.id),  # should support string ids
                            "order": 0,
                            "entity_type": "actions",
                            "properties": [
                                {"key": "bonk", "value": "bonk"},
                                {"key": "id", "value": cohort_extra.id, "type": "cohort"},
                                {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
                                {"key": "bonk-person", "value": "bonk", "type": "person"},
                            ],
                        }
                    ],
                    "filter_test_accounts": False,
                }
            },
        )

        created_experiment = response.json()["id"]

        journeys_for(
            {
                "person1": [
                    {
                        "event": "insight viewed",
                        "timestamp": datetime.now() - timedelta(days=2),
                        "properties": {"$current_url": "x", "bonk": "bonk", "filters_count": 2},
                    },
                ],
                "person2": [
                    {
                        "event": "insight viewed",
                        "timestamp": datetime.now() - timedelta(days=2),
                        "properties": {
                            "$current_url": "y",
                            "bonk": "bonk",
                            "insight": "RETENTION",
                        },  # missing pageview person property
                    },
                ],
                "person2-no-bonk": [
                    {
                        "event": "insight viewed",
                        "timestamp": datetime.now() - timedelta(days=2),
                        "properties": {"$current_url": "y", "filters_count": 3},
                    },
                ],
                "person2-not-in-prop": [
                    {
                        "event": "$autocapture",
                        "timestamp": datetime.now() - timedelta(days=2),
                        "properties": {
                            "$current_url": "https://posthog.com/feedback/1234"
                        },  # can't match because clashing current_url filters
                    },
                ],
            },
            self.team,
        )

        _create_person(
            distinct_ids=["1"],
            team_id=self.team.pk,
            properties={"$pageview": "http://example.com"},
        )
        _create_event(
            event="insight viewed",
            team=self.team,
            distinct_id="1",
            properties={"insight": "RETENTION", "$current_url": "x", "bonk": "bonk"},
            timestamp=datetime.now() - timedelta(days=2),
        )
        _create_person(
            distinct_ids=["2"],
            team_id=self.team.pk,
            properties={"$pageview": "http://example.com"},
        )
        _create_event(
            event="insight viewed",
            team=self.team,
            distinct_id="2",
            properties={"insight": "RETENTION", "$current_url": "x"},
            timestamp=datetime.now() - timedelta(days=2),
        )
        flush_persons_and_events()

        cohort_extra.calculate_people_ch(pending_version=1)

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        cohort = response.json()["cohort"]
        self.assertEqual(cohort["name"], 'Users exposed to experiment "Test Experiment"')
        self.assertEqual(cohort["experiment_set"], [created_experiment])

        self.maxDiff = None
        target_filter = cohort["filters"]["properties"]["values"][0]["values"][0]
        self.assertEqual(
            target_filter["event_filters"],
            [
                {"key": "bonk", "type": "event", "value": "bonk"},
                {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
            ],
            cohort["filters"],
        )
        self.assertEqual(
            target_filter["event_type"],
            "actions",
        )
        self.assertEqual(
            target_filter["key"],
            action1.id,
        )
        self.assertEqual(
            target_filter["type"],
            "behavioral",
        )
        self.assertEqual(
            target_filter["value"],
            "performed_event",
        )
        explicit_datetime = parser.isoparse(target_filter["explicit_datetime"])

        self.assertTrue(
            explicit_datetime <= datetime.now(UTC) - timedelta(days=5)
            and explicit_datetime >= datetime.now(UTC) - timedelta(days=5, hours=1)
        )

        cohort_id = cohort["id"]

        while cohort["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")
            cohort = response.json()

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/persons/?cohort={cohort_id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(["1", "person1"], sorted([res["name"] for res in response.json()["results"]]))

    def test_create_exposure_cohort_for_experiment_with_invalid_action_filters_exposure(self):
        response = self._generate_experiment(
            "2024-01-01T10:23",
            {
                "custom_exposure_filter": {
                    "actions": [
                        {
                            "id": "oogabooga",
                            "order": 0,
                            "entity_type": "actions",
                            "properties": [
                                {"key": "bonk", "value": "bonk"},
                                {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
                                {"key": "bonk-person", "value": "bonk", "type": "person"},
                            ],
                        }
                    ],
                    "filter_test_accounts": False,
                }
            },
        )

        created_experiment = response.json()["id"]

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Invalid action ID")

    def test_create_exposure_cohort_for_experiment_with_draft_experiment(self):
        response = self._generate_experiment(None)

        created_experiment = response.json()["id"]

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Experiment does not have a start date")

    def test_create_exposure_cohort_for_experiment_with_existing_cohort(self):
        response = self._generate_experiment()

        created_experiment = response.json()["id"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # now call to make cohort again
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Experiment already has an exposure cohort")

    def test_create_experiment_with_stats_config(self) -> None:
        """Test that stats_config can be passed from frontend and is preserved"""
        ff_key = "stats-config-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Stats Config Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {},
                "stats_config": {
                    "method": "bayesian",
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Stats Config Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        # Verify stats_config is preserved with custom fields
        stats_config = response.json()["stats_config"]
        self.assertEqual(stats_config["method"], "bayesian")

    def test_experiment_activity_logging_shows_correct_user_for_updates(self):
        """Test that experiment activity logs show the correct user for both creation and updates."""

        # Create a second user to test with
        second_user = User.objects.create_user(
            email="second@posthog.com", password="testpass123", first_name="Second", last_name="User"
        )
        self.organization.members.add(second_user)

        # Create experiment with first user (self.user)
        ff_key = "activity-logging-test"
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Activity Logging Test Experiment",
                "description": "Testing activity logging fix",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {},
            },
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        experiment_id = create_response.json()["id"]

        # Check creation activity log shows first user
        creation_logs = ActivityLog.objects.filter(
            scope="Experiment", item_id=str(experiment_id), activity="created"
        ).order_by("-created_at")
        self.assertEqual(len(creation_logs), 1)
        self.assertEqual(creation_logs[0].user, self.user)

        # Switch to second user and update the experiment
        self.client.force_login(second_user)
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "description": "Updated description by second user",
            },
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        # Check update activity log shows second user (not the creator)
        update_logs = ActivityLog.objects.filter(
            scope="Experiment", item_id=str(experiment_id), activity="updated"
        ).order_by("-created_at")
        self.assertEqual(len(update_logs), 1)
        self.assertEqual(update_logs[0].user, second_user)

        # Verify the fix: the update activity log should NOT show the first user
        self.assertNotEqual(update_logs[0].user, self.user)

    def test_experiment_saved_metric_activity_logging_shows_correct_user_for_updates(self):
        """Test that experiment saved metric activity logs show the correct user for both creation and updates."""

        # Create a second user to test with
        second_user = User.objects.create_user(
            email="second@posthog.com", password="testpass123", first_name="Second", last_name="User"
        )
        self.organization.members.add(second_user)

        # Create experiment saved metric with first user (self.user)
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Activity Logging Test Metric",
                "description": "Testing saved metric activity logging fix",
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
                },
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        metric_id = create_response.json()["id"]

        # Check creation activity log shows first user
        creation_logs = ActivityLog.objects.filter(
            scope="Experiment",  # Note: ExperimentSavedMetric logs under "Experiment" scope
            item_id=str(metric_id),
            activity="created",
        ).order_by("-created_at")
        self.assertEqual(len(creation_logs), 1)
        self.assertEqual(creation_logs[0].user, self.user)

        # Switch to second user and update the metric
        self.client.force_login(second_user)
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/{metric_id}/",
            {
                "description": "Updated description by second user",
            },
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        # Check update activity log shows second user (not the creator)
        update_logs = ActivityLog.objects.filter(
            scope="Experiment",  # Note: ExperimentSavedMetric logs under "Experiment" scope
            item_id=str(metric_id),
            activity="updated",
        ).order_by("-created_at")
        self.assertEqual(len(update_logs), 1)
        self.assertEqual(update_logs[0].user, second_user)

        # Verify the fix: the update activity log should NOT show the first user
        self.assertNotEqual(update_logs[0].user, self.user)
