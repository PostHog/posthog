from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest import mock

from rest_framework import status

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.endpoints.backend.tests.conftest import create_endpoint_with_version


def _find_endpoint_feature_call(spy: mock.MagicMock):
    """Return the tag_queries call that set both product=ENDPOINTS and feature=...

    Only `_execute_query_and_respond` and `get_endpoints_last_execution_times`
    set both kwargs together; other endpoint-side tag_queries calls only set
    workload/warehouse_query/endpoint_version/client_query_id.
    """
    for call in spy.call_args_list:
        if call.kwargs.get("product") == Product.ENDPOINTS and "feature" in call.kwargs:
            return call
    return None


class TestEndpointQueryTagging(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.endpoint = create_endpoint_with_version(
            name="taggy",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            created_by=self.user,
            is_active=True,
        )
        self.run_url = f"/api/environments/{self.team.id}/endpoints/{self.endpoint.name}/run/"
        self.last_exec_url = f"/api/environments/{self.team.id}/endpoints/last_execution_times/"

        self.api_key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="tag-test",
            user=self.user,
            secure_value=hash_key_value(self.api_key_value),
            scopes=["*"],
        )

    def test_run_via_session_auth_tags_endpoint_playground(self):
        with mock.patch("products.endpoints.backend.api.tag_queries", wraps=tag_queries) as spy:
            response = self.client.post(self.run_url, {}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        call = _find_endpoint_feature_call(spy)
        assert call is not None, f"no tag_queries(product=ENDPOINTS, feature=...) call found: {spy.call_args_list}"
        assert call.kwargs["feature"] == Feature.ENDPOINT_PLAYGROUND

    def test_run_via_personal_api_key_tags_endpoint_execution(self):
        self.client.logout()
        with mock.patch("products.endpoints.backend.api.tag_queries", wraps=tag_queries) as spy:
            response = self.client.post(
                self.run_url,
                {},
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {self.api_key_value}",
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        call = _find_endpoint_feature_call(spy)
        assert call is not None, f"no tag_queries(product=ENDPOINTS, feature=...) call found: {spy.call_args_list}"
        assert call.kwargs["feature"] == Feature.ENDPOINT_EXECUTION

    def test_last_execution_times_tags_endpoint_last_execution(self):
        with mock.patch("products.endpoints.backend.api.tag_queries", wraps=tag_queries) as spy:
            response = self.client.post(self.last_exec_url, {"names": [self.endpoint.name]}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        call = _find_endpoint_feature_call(spy)
        assert call is not None, f"no tag_queries(product=ENDPOINTS, feature=...) call found: {spy.call_args_list}"
        assert call.kwargs["feature"] == Feature.ENDPOINT_LAST_EXECUTION
