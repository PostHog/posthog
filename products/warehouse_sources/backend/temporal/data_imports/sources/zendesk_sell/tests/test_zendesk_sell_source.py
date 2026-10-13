from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.source import ZendeskSellSource


class TestValidateCredentials:
    @parameterized.expand(
        [("valid", True, (True, None)), ("invalid", False, (False, "Invalid Zendesk Sell access token"))]
    )
    def test_validate_credentials(self, _name: str, probe_result: bool, expected: tuple[bool, str | None]) -> None:
        config = MagicMock(access_token="token")
        with patch.object(source_module, "validate_zendesk_sell_credentials", return_value=probe_result):
            assert ZendeskSellSource().validate_credentials(config, team_id=1) == expected


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.getbase.com/v2/contacts?per_page=100",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.getbase.com/v2/deals?per_page=100"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = ZendeskSellSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.getbase.com/v2/contacts"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.getbase.com/v2/deals"),
            ("read_timeout", "HTTPSConnectionPool(host='api.getbase.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = ZendeskSellSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestSourceForPipeline:
    def test_plumbs_config_and_inputs_into_source_response(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        sentinel = SourceResponse(name="deals", items=lambda: iter(()), primary_keys=["id"])

        def fake_source(**kwargs: Any) -> SourceResponse:
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(source_module, "zendesk_sell_source", fake_source)

        config = MagicMock(access_token="my-token")
        manager = MagicMock()
        inputs = MagicMock(schema_name="deals")
        inputs.logger = MagicMock()

        result = ZendeskSellSource().source_for_pipeline(config, manager, inputs)

        assert result is sentinel
        assert captured["access_token"] == "my-token"
        assert captured["endpoint"] == "deals"
        assert captured["resumable_source_manager"] is manager


class TestCanonicalDescriptions:
    def test_descriptions_key_off_known_endpoints(self) -> None:
        descriptions = ZendeskSellSource().get_canonical_descriptions()
        assert descriptions  # non-empty
        # Every documented entry must map to a real endpoint name so enrichment lands on the table.
        assert set(descriptions).issubset(set(ENDPOINTS))
        for entry in descriptions.values():
            assert entry["description"]
            assert entry["docs_url"].startswith("https://")
