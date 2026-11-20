from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest import mock

from rest_framework import status

from posthog.api.services.query import process_query_model
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags, tag_queries
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.endpoints.backend.tests.conftest import create_endpoint_with_version


def _find_endpoint_feature_call(spy: mock.MagicMock):
    """Return the tag_queries call that set both product=ENDPOINTS and feature=...

    Only `_execute_query_and_respond` sets both kwargs together; other endpoint-side tag_queries calls
    only set workload/warehouse_query/endpoint_version/client_query_id.
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

        self.api_key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="tag-test",
            user=self.user,
            secure_value=hash_key_value(self.api_key_value),
            scopes=["*"],
        )

    def test_run_via_session_auth_tags_endpoint_playground(self):
        with mock.patch("products.endpoints.backend.logic.execution.tag_queries", wraps=tag_queries) as spy:
            response = self.client.post(self.run_url, {}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        call = _find_endpoint_feature_call(spy)
        assert call is not None, f"no tag_queries(product=ENDPOINTS, feature=...) call found: {spy.call_args_list}"
        assert call.kwargs["feature"] == Feature.ENDPOINT_PLAYGROUND

    def test_run_via_personal_api_key_tags_endpoint_execution(self):
        self.client.logout()
        with mock.patch("products.endpoints.backend.logic.execution.tag_queries", wraps=tag_queries) as spy:
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

    def test_run_tags_its_query_with_the_execution_id_of_its_log_entry(self):
        self.client.logout()
        execution_ids_at_query_time = []

        def run_query(*args, **kwargs):
            execution_ids_at_query_time.append(get_query_tags().endpoint_execution_id)
            return process_query_model(*args, **kwargs)

        with (
            mock.patch("products.endpoints.backend.logic.execution.process_query_model", side_effect=run_query),
            mock.patch("products.endpoints.backend.logs.get_producer") as get_producer,
        ):
            response = self.client.post(
                self.run_url,
                {"limit": 5},
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {self.api_key_value}",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        execution_id = response.json()["execution_id"]
        assert execution_ids_at_query_time == [execution_id]
        [log_entry] = [call.kwargs["data"] for call in get_producer.return_value.produce.call_args_list]
        assert log_entry["instance_id"] == execution_id
        assert "refresh=cache access=personal_api_key limit=5" in log_entry["message"]
