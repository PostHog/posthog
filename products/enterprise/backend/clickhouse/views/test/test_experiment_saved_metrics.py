from rest_framework import status

from posthog.models.experiment import Experiment, ExperimentToSavedMetric

from products.enterprise.backend.api.test.base import APILicensedTest


class TestExperimentSavedMetricsCRUD(APILicensedTest):
    def test_can_list_experiment_saved_metrics(self):
        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_validation_of_query_metric(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Query is required to create a saved metric")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {"not-kind": "ExperimentTrendsQuery"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Metric query kind must be 'ExperimentMetric', 'ExperimentTrendsQuery' or 'ExperimentFunnelsQuery'",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {"kind": "not-ExperimentTrendsQuery"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Metric query kind must be 'ExperimentMetric', 'ExperimentTrendsQuery' or 'ExperimentFunnelsQuery'",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {"kind": "TrendsQuery"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Metric query kind must be 'ExperimentMetric', 'ExperimentTrendsQuery' or 'ExperimentFunnelsQuery'",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {"kind": "ExperimentTrendsQuery"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue("'loc': ('count_query',), 'msg': 'Field required'" in response.json()["detail"])

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_update_experiment_saved_metrics(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {
                        "kind": "TrendsQuery",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    },
                },
                "tags": ["tag1"],
            },
            format="json",
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
        self.assertEqual(response.json()["tags"], ["tag1"])
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

        # Now try updating saved metric
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/{saved_metric_id}",
            {
                "name": "Test Experiment saved metric 2",
                "description": "Test description 2",
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageleave"}]},
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Test Experiment saved metric 2")
        self.assertEqual(
            response.json()["query"],
            {
                "kind": "ExperimentTrendsQuery",
                "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageleave"}]},
            },
        )

        # make sure experiment in question was updated as well
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 1)
        saved_metric = Experiment.objects.get(pk=exp_id).saved_metrics.first()
        self.assertEqual(saved_metric.id, saved_metric_id)
        self.assertEqual(
            saved_metric.query,
            {
                "kind": "ExperimentTrendsQuery",
                "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageleave"}]},
            },
        )
        self.assertEqual(saved_metric.name, "Test Experiment saved metric 2")
        self.assertEqual(saved_metric.description, "Test description 2")

        # now delete saved metric
        response = self.client.delete(f"/api/projects/{self.team.id}/experiment_saved_metrics/{saved_metric_id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # make sure experiment in question was updated as well
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 0)
        self.assertEqual(ExperimentToSavedMetric.objects.filter(experiment_id=exp_id).count(), 0)

    def test_create_saved_metric_with_experiment_metric(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {
                        "kind": "EventsNode",
                        "event": "$pageview",
                    },
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment saved metric")
        self.assertEqual(response.json()["description"], "Test description")
        self.assertEqual(response.json()["query"]["kind"], "ExperimentMetric")
        self.assertEqual(response.json()["query"]["metric_type"], "mean")

    def test_create_saved_metric_with_experiment_metric_invalid_metric_type(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "invalid",
                    "source": {
                        "kind": "EventsNode",
                        "event": "$pageview",
                    },
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("ExperimentMetric metric_type must be 'mean', 'funnel', or 'ratio'", response.json()["detail"])

    def test_create_saved_metric_with_experiment_metric_ratio(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment ratio metric",
                "description": "Test description for ratio",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "ratio",
                    "numerator": {
                        "kind": "EventsNode",
                        "event": "$purchase",
                    },
                    "denominator": {
                        "kind": "EventsNode",
                        "event": "$pageview",
                    },
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment ratio metric")
        self.assertEqual(response.json()["description"], "Test description for ratio")
        self.assertEqual(response.json()["query"]["kind"], "ExperimentMetric")
        self.assertEqual(response.json()["query"]["metric_type"], "ratio")
        self.assertEqual(response.json()["query"]["numerator"]["event"], "$purchase")
        self.assertEqual(response.json()["query"]["denominator"]["event"], "$pageview")

    def test_create_saved_metric_with_experiment_metric_ratio_missing_fields(self):
        # Test missing numerator
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment ratio metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "ratio",
                    "denominator": {
                        "kind": "EventsNode",
                        "event": "$pageview",
                    },
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue("'loc': ('numerator',), 'msg': 'Field required'" in response.json()["detail"])

        # Test missing denominator
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment ratio metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "ratio",
                    "numerator": {
                        "kind": "EventsNode",
                        "event": "$purchase",
                    },
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue("'loc': ('denominator',), 'msg': 'Field required'" in response.json()["detail"])

    def test_invalid_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": None,  # invalid
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "This field may not be null.")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "xyz",
                "query": {},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Query is required to create a saved metric")
