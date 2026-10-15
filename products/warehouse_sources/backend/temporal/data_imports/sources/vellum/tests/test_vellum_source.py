from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.source import VellumSource


class TestVellumSchemas:
    def test_names_filter(self) -> None:
        schemas = VellumSource().get_schemas(MagicMock(), team_id=1, names=["documents"])
        assert [s.name for s in schemas] == ["documents"]


class TestVellumValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, 200), True, None),
            ("bad_key_403", (False, 403), False, "Invalid Vellum API key"),
            ("unauthorized_401", (False, 401), False, "Invalid Vellum API key"),
            ("network_error", (False, None), False, "Could not connect to Vellum. Please try again later."),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_result: tuple[bool, int | None], expected_ok: bool, expected_msg: str | None
    ) -> None:
        source = VellumSource()
        config = MagicMock(api_key="test-key")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.vellum.source.check_credentials",
            return_value=probe_result,
        ):
            ok, msg = source.validate_credentials(config, team_id=1)
        assert ok is expected_ok
        assert msg == expected_msg


class TestVellumNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.vellum.ai/v1/documents?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.vellum.ai/v1/document-indexes"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        assert any(key in observed_error for key in VellumSource().get_non_retryable_errors())

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.vellum.ai', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.vellum.ai/v1/documents"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.vellum.ai/v1/documents"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        assert not any(key in other_error for key in VellumSource().get_non_retryable_errors())
