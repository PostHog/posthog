from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.todoist import (
    TodoistSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.source import TodoistSource


class TestTodoistSource:
    def setup_method(self) -> None:
        self.source = TodoistSource()
        self.team_id = 123
        self.config = TodoistSourceConfig(api_token="tok-test")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Todoist"
        assert config.label == "Todoist"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert len(config.fields) == 1

        token_field = config.fields[0]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.name == "api_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        # The token is sent to the API, so it must be stored as a secret.
        assert token_field.secret is True

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Each declared endpoint should ship a curated description so it isn't sent to the LLM.
        described = set(self.source.get_canonical_descriptions().keys())
        assert set(ENDPOINTS).issubset(described)

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.todoist.com/api/v1/tasks?limit=200",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.todoist.com/api/v1/projects",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.todoist.com', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.todoist.com/api/v1/tasks"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.todoist.com/api/v1/tasks"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_validate_credentials_success(self) -> None:
        with mock.patch.object(source_module, "validate_todoist_credentials", return_value=True) as probe:
            ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is True
        assert error is None
        probe.assert_called_once_with("tok-test")

    def test_validate_credentials_failure(self) -> None:
        with mock.patch.object(source_module, "validate_todoist_credentials", return_value=False):
            ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is False
        assert error == "Invalid Todoist API token"
