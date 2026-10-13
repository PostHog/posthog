from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.replyio import (
    ReplyIoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.reply_io import ReplyIoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.source import ReplyIoSource


class TestReplyIoSource:
    def setup_method(self) -> None:
        self.source = ReplyIoSource()
        self.team_id = 123
        self.config = ReplyIoSourceConfig(api_key="reply-key")

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.reply.io/v3/contacts?top=1000"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.reply.io/v3/sequences?top=1000"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.reply.io/v3/contacts"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.reply.io/v3/tasks"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            ("source_create_probes_whoami", None, "/v3/whoami"),
            ("known_schema_probes_its_endpoint", "contacts", "/v3/contacts"),
            ("unknown_schema_falls_back_to_whoami", "not_a_table", "/v3/whoami"),
        ]
    )
    def test_validate_credentials_delegates(self, _name: str, schema_name: str | None, expected_path: str) -> None:
        with scripted_network(always(ScriptedResponse(json={}))) as network:
            result = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert result == (True, None)
        assert [request.path for request in network.requests_log] == [expected_path]
        assert network.requests_log[0].headers["authorization"] == "Bearer reply-key"

    @parameterized.expand(
        [
            ("reachable", 200, {"contacts": None}),
            ("missing_scope", 403, {"contacts": "Your Reply API key is missing the `contacts:read` scope"}),
        ]
    )
    def test_get_endpoint_permissions_delegates(self, _name: str, status: int, expected: dict[str, str | None]) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            result = self.source.get_endpoint_permissions(self.config, self.team_id, ["contacts"])

        assert result == expected
        assert network.requests_log[0].headers["authorization"] == "Bearer reply-key"

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "contacts",
            [ScriptedResponse(json={"items": [], "hasMore": False})],
            resume_state=ReplyIoResumeConfig(skip=200),
        )

        assert result.paths == ["/v3/contacts"]
        assert result.requests[0].headers["authorization"] == "Bearer reply-key"
        # The resume manager reaches the extraction: the first page is the saved offset.
        assert result.params("skip") == ["200"]

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        result = SourceDriver(self.source, self.config).run("not_a_table", [])

        assert isinstance(result.raised, ValueError)
        assert "Unknown Reply.io schema 'not_a_table'" in str(result.raised)
