from posthog.test.base import APIBaseTest

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
