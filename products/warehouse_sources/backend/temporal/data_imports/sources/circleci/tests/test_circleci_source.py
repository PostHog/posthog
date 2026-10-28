from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.source import CircleCISource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.circleci import (
    CircleCISourceConfig,
)


class TestCircleCISource:
    def setup_method(self):
        self.source = CircleCISource()
        self.team_id = 123
        self.config = CircleCISourceConfig(api_token="circle-token", org_slug="gh/posthog")

    @parameterized.expand(
        [
            ("404 Client Error: Not Found for url: https://circleci.com/api/v2/project/gh/posthog/posthog",),
        ]
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",),
        ]
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_no_endpoint_advertises_incremental(self, endpoint):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        # No CircleCI v2 list endpoint has a server-side timestamp filter, so all are full refresh.
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False
        assert schemas[endpoint].incremental_fields == []
        assert INCREMENTAL_FIELDS.get(endpoint) is None

    @parameterized.expand(
        [
            ("v2", "/api/v2/pipeline"),
            ("v3", "/api/v3/projects"),
            # An unpinned call (pre-creation validation) resolves to the v3 default.
            (None, "/api/v3/projects"),
        ]
    )
    def test_validate_credentials_probes_the_pinned_api(self, api_version, expected_org_probe_path):
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/api/v2/me/collaborations":
                return ScriptedResponse(json=[{"id": "org-uuid", "slug": "gh/posthog"}])
            return ScriptedResponse(json={})

        with scripted_network(answer) as network:
            assert self.source.validate_credentials(self.config, self.team_id, api_version=api_version) == (True, None)

        assert network.requests_log[-1].path == expected_org_probe_path
