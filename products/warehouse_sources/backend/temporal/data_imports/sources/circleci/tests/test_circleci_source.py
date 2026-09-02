from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.source import CircleCISource
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
            ("401 Client Error: Unauthorized for url: https://circleci.com/api/v2/pipeline?org-slug=gh%2Fposthog",),
            ("403 Client Error: Forbidden for url: https://circleci.com/api/v2/workflow/abc/job",),
            ("404 Client Error: Not Found for url: https://circleci.com/api/v2/project/gh/posthog/posthog",),
        ]
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",),
            ("500 Server Error for url: https://circleci.com/api/v2/pipeline",),
            ("429 Client Error: Too Many Requests for url: https://circleci.com/api/v2/pipeline",),
        ]
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_no_endpoint_advertises_incremental(self, endpoint):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        # No CircleCI v2 list endpoint has a server-side timestamp filter, so all are full refresh.
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False
        assert schemas[endpoint].incremental_fields == []
        assert INCREMENTAL_FIELDS.get(endpoint) is None

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["pipelines"])
        assert len(schemas) == 1
        assert schemas[0].name == "pipelines"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []
