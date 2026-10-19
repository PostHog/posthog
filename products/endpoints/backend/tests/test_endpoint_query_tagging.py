from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest import mock

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.instance_setting import override_instance_config
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

    @parameterized.expand([(None, False), (True, False), (True, True)])
    def test_run_via_session_auth_tags_endpoint_playground(self, native: bool | None, warm_cache: bool):
        version = self.endpoint.get_version()
        assert version is not None
        if native is not None:
            version.query["modifiers"] = {"useNewEventsCluster": native}
            version.save()
        with (
            override_instance_config("CLICKHOUSE_NATIVE_EVENTS_HOST", "native.example.com"),
            override_instance_config("CLICKHOUSE_NATIVE_EVENTS_TEAMS", [self.team.pk]),
            mock.patch("posthog.hogql.query.sync_execute", return_value=([(1,)], [("1", "UInt8")])) as execute,
            mock.patch("products.endpoints.backend.logic.execution.tag_queries", wraps=tag_queries) as spy,
        ):
            if warm_cache:
                response = self.client.post(
                    f"/api/projects/{self.team.id}/query/",
                    {"query": version.query, "refresh": "force_blocking", "async": False},
                    format="json",
                )
                assert response.status_code == status.HTTP_200_OK, response.json()
                execute.reset_mock()
            response = self.client.post(self.run_url, {}, format="json")
        if native:
            assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
            assert "not support native events cluster" in str(response.json())
            execute.assert_not_called()
            return
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
