from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.source import DecagonSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.decagon import (
    DecagonSourceConfig,
)


class TestDecagonSource:
    def setup_method(self) -> None:
        self.source = DecagonSource()
        self.team_id = 123
        self.config = DecagonSourceConfig(api_key="decagon-test-key")

    def test_get_schemas_filtered_by_names(self) -> None:
        assert [s.name for s in self.source.get_schemas(self.config, self.team_id, names=["conversations"])] == [
            "conversations"
        ]
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @parameterized.expand(
        [
            (
                "connection_error_wrapping_read_timeout",
                "HTTPSConnectionPool(host='api.decagon.ai', port=443): Max retries exceeded with url: "
                "/conversation/export (Caused by ReadTimeoutError(\"HTTPSConnectionPool(host='api.decagon.ai', "
                'port=443): Read timed out. (read timeout=60)"))',
            ),
            (
                "exhausted_retryable_status",
                "Decagon API error (retryable): status=503, url=https://api.decagon.ai/tag/all",
            ),
        ]
    )
    def test_retryable_errors_cover_exhausted_transient_failures(self, _name: str, error_msg: str) -> None:
        # fetch_page already retries these with backoff; once that budget exhausts they must
        # stay classified as retryable (self-recovering via Temporal) rather than tracked
        # exception noise.
        assert error_message_matches(error_msg, self.source.get_retryable_errors())

    @parameterized.expand(
        [
            (
                "agent_assist_403_names_the_plan_gate",
                "403 Client Error: Forbidden for url: "
                "https://api.decagon.ai/agent_assist/actions/export?min_timestamp=0",
                "Agent Assist",
            ),
            (
                "other_endpoint_403_keeps_the_generic_message",
                "403 Client Error: Forbidden for url: https://api.decagon.ai/tag/all",
                "endpoint behind this table",
            ),
            (
                "401_still_maps_to_the_key_message",
                "401 Client Error: Unauthorized for url: https://api.decagon.ai/conversation/export",
                "rejected the API key",
            ),
            (
                "contract_mismatch_points_at_support_not_the_key",
                "Decagon imported no rows against a nonzero reported total: articles reports 12 rows "
                "and the walk kept none. Check the response envelope against the endpoint config.",
                "Contact support",
            ),
            (
                "unreadable_envelope_points_at_support_not_the_key",
                "Decagon sent lists this table's config cannot read as rows: tags carries 2 list(s) and "
                "2 of them carry this endpoint's primary keys ('drafts', 'published').",
                "Contact support",
            ),
        ]
    )
    def test_non_retryable_errors_surface_the_most_specific_message(
        self, _name: str, error_msg: str, expected_fragment: str
    ) -> None:
        # Mirrors the finalization activity: the first matching pattern in insertion order
        # decides the message the operator sees, so the agent_assist entry must win over the
        # bare 403 fallback for its own URL and lose it for every other endpoint.
        friendly = next(
            (
                message
                for pattern, message in self.source.get_non_retryable_errors().items()
                if error_message_matches(error_msg, [pattern])
            ),
            None,
        )
        assert friendly is not None
        assert expected_fragment in friendly

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.decagon.source.validate_decagon_credentials"
    )
    def test_validate_credentials(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = True
        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        mock_validate.return_value = False
        is_valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is False
        assert message is not None

        mock_validate.assert_called_with(self.config.api_key)

    # The second case guards the null-out: a watermark left over from an earlier
    # incremental configuration must not window a sync that is no longer incremental,
    # or the full refresh silently drops every row older than the stale watermark.
