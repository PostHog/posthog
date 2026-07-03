from posthog.test.base import APIBaseTest

from rest_framework import status

from products.data_modeling.backend.facade.internal_ops import mint_data_modeling_ops_token
from products.data_modeling.backend.facade.models import DataModelingJob, DataWarehouseSavedQuery
from products.endpoints.backend.models import Endpoint, EndpointVersion


class TestInternalEndpointsOpsAPI(APIBaseTest):
    def _get(self, path: str, token: str | None = None):
        base = f"/api/projects/{self.team.id}/internal/data_modeling_ops"
        kwargs = {}
        if token is not None:
            kwargs["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return self.client.get(f"{base}{path}", **kwargs)

    def _token(self) -> str:
        return mint_data_modeling_ops_token(team_id=self.team.id, acting_user="test@posthog.com")

    def test_rejects_missing_token(self):
        response = self._get("/endpoints")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_endpoint_detail_reports_job_derived_freshness_when_last_run_at_is_unwritten(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_endpoint_v1",
            query={"query": "select 1"},
            is_materialized=True,
            last_run_at=None,
        )
        endpoint = Endpoint.objects.create(team=self.team, name="my_endpoint", created_by=self.user)
        EndpointVersion.objects.create(
            endpoint=endpoint,
            team=self.team,
            version=1,
            query={"kind": "HogQLQuery", "query": "select 1"},
            saved_query=saved_query,
        )
        job = DataModelingJob.objects.create(
            team=self.team,
            saved_query=saved_query,
            status=DataModelingJob.Status.COMPLETED,
        )

        response = self._get("/endpoints/my_endpoint", self._token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["name"], "my_endpoint")
        self.assertEqual(len(data["versions"]), 1)
        version = data["versions"][0]
        self.assertEqual(version["saved_query_id"], str(saved_query.id))
        self.assertIsNone(version["saved_query_last_run_at"])
        self.assertEqual(version["last_successful_job_at"], job.updated_at.isoformat())

    def test_endpoints_list(self):
        Endpoint.objects.create(team=self.team, name="a_endpoint", created_by=self.user)
        Endpoint.objects.create(team=self.team, name="b_endpoint", created_by=self.user, is_active=False)

        response = self._get("/endpoints", self._token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual([e["name"] for e in results], ["a_endpoint", "b_endpoint"])
        self.assertFalse(results[1]["is_active"])
