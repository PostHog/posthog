from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.circleci import CircleCIResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.source import CircleCISource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CircleCISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCircleCISource:
    def setup_method(self):
        self.source = CircleCISource()
        self.team_id = 123
        self.config = CircleCISourceConfig(api_token="circle-token", org_slug="gh/posthog")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CIRCLECI

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "CircleCI"
        assert config.label == "CircleCI"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/circleci.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token", "org_slug"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_org_slug_field_is_required_text(self):
        config = self.source.get_source_config
        org_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "org_slug")
        assert org_field.type == SourceFieldInputConfigType.TEXT
        assert org_field.secret is False
        assert org_field.required is True

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

    @parameterized.expand(
        [
            ((True, None), True, None),
            ((False, "Invalid CircleCI API token. Please check your personal API token."), False, "Invalid"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.circleci.source.validate_circleci_credentials"
    )
    def test_validate_credentials(self, mock_return, expected_valid, expected_message_prefix, mock_validate):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_message_prefix is None:
            assert error_message is None
        else:
            assert error_message is not None
            assert error_message.startswith(expected_message_prefix)
        mock_validate.assert_called_once_with(self.config.api_token, self.config.org_slug)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CircleCIResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.circleci.source.circleci_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_circleci_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "pipelines"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_circleci_source.assert_called_once()
        kwargs = mock_circleci_source.call_args.kwargs
        assert kwargs["api_token"] == "circle-token"
        assert kwargs["org_slug"] == "gh/posthog"
        assert kwargs["endpoint"] == "pipelines"
        assert kwargs["logger"] is inputs.logger
        assert kwargs["resumable_source_manager"] is manager
