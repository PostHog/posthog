import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized
from rest_framework import status

from products.llm_analytics.backend.models.clustering_job import ClusteringJob


class TestClusteringJobViewSet(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        base = f"/api/environments/{self.team.id}/llm_analytics/clustering_jobs/"
        return f"{base}{suffix}" if suffix else base

    def _create_job(self, **kwargs) -> ClusteringJob:
        defaults = {
            "team": self.team,
            "name": "Test Job",
            "analysis_level": "trace",
            "event_filters": [],
            "enabled": True,
        }
        defaults.update(kwargs)
        return ClusteringJob.objects.create(**defaults)

    def test_unauthenticated_user_cannot_access(self):
        self.client.logout()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_returns_empty_when_no_jobs(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

    def test_list_returns_jobs_ordered_by_created_at(self):
        self._create_job(name="First")
        self._create_job(name="Second")
        response = self.client.get(self._url())
        names = [j["name"] for j in response.json()["results"]]
        self.assertEqual(names, ["First", "Second"])

    def test_create_job(self):
        response = self.client.post(
            self._url(),
            {"name": "Prod Traffic", "analysis_level": "trace", "event_filters": [], "enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Prod Traffic")
        self.assertEqual(ClusteringJob.objects.filter(team=self.team).count(), 1)

    def test_create_job_with_filters(self):
        filters = [{"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"}]
        response = self.client.post(
            self._url(),
            {"name": "GPT-4 Only", "analysis_level": "generation", "event_filters": filters, "enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        job = ClusteringJob.objects.get(id=response.json()["id"])
        self.assertEqual(job.event_filters, filters)
        self.assertEqual(job.analysis_level, "generation")

    def test_create_enforces_max_5_jobs(self):
        for i in range(5):
            self._create_job(name=f"Job {i}")

        response = self.client.post(
            self._url(),
            {"name": "Too Many", "analysis_level": "trace"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Maximum", response.json()["detail"])

    def test_create_enforces_unique_name_per_team(self):
        self._create_job(name="Duplicate")
        response = self.client.post(
            self._url(),
            {"name": "Duplicate", "analysis_level": "trace"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already exists", response.json()["detail"])

    def test_partial_update(self):
        job = self._create_job(name="Old Name")
        response = self.client.patch(
            self._url(f"{job.id}/"),
            {"name": "New Name"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        job.refresh_from_db()
        self.assertEqual(job.name, "New Name")

    def test_update_enabled_toggle(self):
        job = self._create_job(enabled=True)
        response = self.client.patch(
            self._url(f"{job.id}/"),
            {"enabled": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        job.refresh_from_db()
        self.assertFalse(job.enabled)

    def test_destroy(self):
        job = self._create_job()
        response = self.client.delete(self._url(f"{job.id}/"))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(ClusteringJob.objects.filter(team=self.team).count(), 0)

    def test_cannot_see_other_teams_jobs(self):
        from posthog.models import Organization, Project, Team

        other_org = Organization.objects.create(name="other")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)
        ClusteringJob.objects.create(team=other_team, name="Other Team Job", analysis_level="trace")

        response = self.client.get(self._url())
        self.assertEqual(response.json()["results"], [])

    @parameterized.expand(
        [
            ("trace",),
            ("generation",),
        ]
    )
    def test_create_with_analysis_level(self, level):
        response = self.client.post(
            self._url(),
            {"name": f"Test {level}", "analysis_level": level},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["analysis_level"], level)

    def test_create_rejects_invalid_analysis_level(self):
        response = self.client.post(
            self._url(),
            {"name": "Bad Level", "analysis_level": "invalid"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_disables_default_job_at_same_level(self):
        default_trace = self._create_job(name="Default - traces", analysis_level="trace", enabled=True)
        default_gen = self._create_job(name="Default - generations", analysis_level="generation", enabled=True)

        response = self.client.post(
            self._url(),
            {"name": "Prod Traffic", "analysis_level": "trace"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        default_trace.refresh_from_db()
        default_gen.refresh_from_db()
        self.assertFalse(default_trace.enabled)
        self.assertTrue(default_gen.enabled)

    def test_update_enforces_unique_name_per_team(self):
        self._create_job(name="Existing Name")
        job = self._create_job(name="Original")
        response = self.client.patch(
            self._url(f"{job.id}/"),
            {"name": "Existing Name"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already exists", response.json()["detail"])

    def test_update_allows_keeping_same_name(self):
        job = self._create_job(name="Keep Me")
        response = self.client.patch(
            self._url(f"{job.id}/"),
            {"name": "Keep Me", "enabled": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_does_not_disable_non_default_jobs(self):
        custom = self._create_job(name="Custom Trace Job", analysis_level="trace", enabled=True)

        response = self.client.post(
            self._url(),
            {"name": "Another Trace Job", "analysis_level": "trace"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        custom.refresh_from_db()
        self.assertTrue(custom.enabled)


class TestClusteringRunWithJobId(APIBaseTest):
    """Tests for clustering_job_id param on the manual clustering run endpoint."""

    _RUN_URL_TEMPLATE = "/api/environments/{team_id}/llm_analytics/clustering_runs/"

    def _run_url(self) -> str:
        return self._RUN_URL_TEMPLATE.format(team_id=self.team.id)

    def _create_job(self, **kwargs) -> ClusteringJob:
        defaults = {
            "team": self.team,
            "name": "Test Job",
            "analysis_level": "trace",
            "event_filters": [],
            "enabled": True,
        }
        defaults.update(kwargs)
        return ClusteringJob.objects.create(**defaults)

    def _minimal_run_payload(self, **kwargs) -> dict:
        payload: dict = {}
        payload.update(kwargs)
        return payload

    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("products.llm_analytics.backend.api.clustering.sync_connect")
    def test_valid_clustering_job_id_overrides_event_filters(self, mock_connect, _mock_flag):
        mock_client = AsyncMock()
        mock_client.start_workflow = AsyncMock(return_value=AsyncMock(id="wf-1", result_run_id="run-1"))
        mock_connect.return_value = mock_client

        filters = [{"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"}]
        job = self._create_job(analysis_level="generation", event_filters=filters)

        response = self.client.post(
            self._run_url(),
            self._minimal_run_payload(clustering_job_id=job.id),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        call_kwargs = mock_client.start_workflow.call_args
        workflow_inputs = call_kwargs[0][1]
        self.assertEqual(workflow_inputs.analysis_level, "generation")
        self.assertEqual(workflow_inputs.event_filters, filters)

    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("products.llm_analytics.backend.api.clustering.sync_connect")
    def test_invalid_clustering_job_id_returns_404(self, mock_connect, _mock_flag):
        response = self.client.post(
            self._run_url(),
            self._minimal_run_payload(clustering_job_id=str(uuid.uuid4())),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_connect.assert_not_called()

    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("products.llm_analytics.backend.api.clustering.sync_connect")
    def test_clustering_job_from_different_team_returns_404(self, mock_connect, _mock_flag):
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_job = ClusteringJob.objects.create(
            team=other_team,
            name="Other Team Job",
            analysis_level="trace",
            event_filters=[],
            enabled=True,
        )

        response = self.client.post(
            self._run_url(),
            self._minimal_run_payload(clustering_job_id=other_job.id),
            format="json",
        )
        # 403 or 404 — either way the cross-team job is not accessible
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        mock_connect.assert_not_called()

    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("products.llm_analytics.backend.api.clustering.sync_connect")
    def test_no_clustering_job_id_uses_request_event_filters(self, mock_connect, _mock_flag):
        mock_client = AsyncMock()
        mock_client.start_workflow = AsyncMock(return_value=AsyncMock(id="wf-1", result_run_id="run-1"))
        mock_connect.return_value = mock_client

        request_filters = [{"key": "$ai_provider", "value": "openai", "operator": "exact", "type": "event"}]
        response = self.client.post(
            self._run_url(),
            self._minimal_run_payload(event_filters=request_filters),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        call_kwargs = mock_client.start_workflow.call_args
        workflow_inputs = call_kwargs[0][1]
        self.assertEqual(workflow_inputs.event_filters, request_filters)
