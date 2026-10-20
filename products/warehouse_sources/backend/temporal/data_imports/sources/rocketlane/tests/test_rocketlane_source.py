from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rocketlane import (
    RocketlaneSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.rocketlane import (
    RocketlaneResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.source import RocketlaneSource


class TestRocketlaneSource:
    def setup_method(self) -> None:
        self.source = RocketlaneSource()
        self.team_id = 123
        self.config = RocketlaneSourceConfig(api_key="rl-key")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.rocketlane.com/api/1.0/projects?pageSize=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.rocketlane.com/api/1.0/tasks?pageSize=100&pageToken=abc",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.rocketlane.com/api/1.0/projects",
            ),
            ("read_timeout", "HTTPSConnectionPool(host='api.rocketlane.com', port=443): Read timed out."),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.rocketlane.com/api/1.0/users"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            ("valid", 200, True, None),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message
        assert network.requests_log[0].headers["api-key"] == "rl-key"

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "projects",
            [ScriptedResponse(json={"data": [], "pagination": {"hasMore": False}})],
            resume_state=RocketlaneResumeConfig(page_token="t2"),
        )

        assert result.requests[0].headers["api-key"] == "rl-key"
        assert result.paths == ["/api/1.0/projects"]
        # The resume manager reaches the extraction: the first request carries the saved token.
        assert result.requests[0].param("pageToken") == "t2"
