from posthog.test.base import APIBaseTest

from rest_framework import status

from products.data_modeling.backend.facade.models import DAG, DataModelingJob, DataWarehouseSavedQuery
from products.data_modeling.backend.tests.api.oidc import OidcAuthTestMixin, mint_oidc_token
from products.endpoints.backend.models import Endpoint, EndpointVersion


class TestInternalEndpointsOpsAPI(OidcAuthTestMixin, APIBaseTest):
    def _get(self, path: str, token: str | None = None):
        base = "/api/internal/data_modeling_ops"
        if token is not None:
            return self.client.get(f"{base}{path}", HTTP_AUTHORIZATION=f"Bearer {token}")
        return self.client.get(f"{base}{path}")

    def _token(self) -> str:
        return mint_oidc_token()

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

        response = self._get(f"/endpoints/{endpoint.id}", self._token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["name"], "my_endpoint")
        self.assertEqual(len(data["versions"]), 1)
        version = data["versions"][0]
        self.assertEqual(version["saved_query_id"], str(saved_query.id))
        self.assertIsNone(version["saved_query_last_run_at"])
        assert job.updated_at is not None
        self.assertEqual(version["last_successful_job_at"], job.updated_at.isoformat())

    def test_endpoints_list(self):
        Endpoint.objects.create(team=self.team, name="a_endpoint", created_by=self.user)
        Endpoint.objects.create(team=self.team, name="b_endpoint", created_by=self.user, is_active=False)

        response = self._get("/endpoints", self._token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual([e["name"] for e in results], ["a_endpoint", "b_endpoint"])
        self.assertFalse(results[1]["is_active"])


class TestInternalResolveAPI(OidcAuthTestMixin, APIBaseTest):
    def _resolve(self, kind: str, q: str, token: str | None = None):
        url = f"/api/internal/data_modeling_ops/resolve?kind={kind}&q={q}"
        if token is not None:
            return self.client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}")
        return self.client.get(url)

    def _fleet_token(self) -> str:
        return mint_oidc_token()

    def test_rejects_session_only_request(self):
        response = self._resolve("name", "anything")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_unknown_kind(self):
        response = self._resolve("mystery", "anything", self._fleet_token())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_name_search_merges_saved_queries_and_endpoints_exact_first(self):
        DataWarehouseSavedQuery.objects.create(team=self.team, name="billing_rollup_daily", query={"query": "select 1"})
        Endpoint.objects.create(team=self.team, name="billing_rollup", created_by=self.user)

        response = self._resolve("name", "billing_rollup", self._fleet_token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        matches = response.json()["matches"]
        self.assertEqual(
            [(m["kind"], m["name"]) for m in matches],
            [("endpoint", "billing_rollup"), ("saved_query", "billing_rollup_daily")],
        )
        self.assertEqual(matches[0]["team_id"], self.team.id)

    def test_schedule_kind_resolves_dag_id_to_owning_dag(self):
        dag = DAG.objects.create(team=self.team, name="Default")

        response = self._resolve("schedule", str(dag.id), self._fleet_token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        matches = response.json()["matches"]
        self.assertEqual([(m["kind"], m["id"]) for m in matches], [("dag", str(dag.id))])
