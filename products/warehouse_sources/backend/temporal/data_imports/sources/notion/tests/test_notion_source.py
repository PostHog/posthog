import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.notion import NotionSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.notion.source import NotionSource

NOTION_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.notion.notion"


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 400


class TestNotionSource:
    def setup_method(self) -> None:
        self.source = NotionSource()

    def test_new_sources_default_to_latest_version(self) -> None:
        # New sources are stamped with default_version, so a regression here silently pins them to
        # the older API. Both versions must stay supported so existing pins keep resolving.
        assert self.source.default_version == "2026-03-11"
        assert set(self.source.supported_versions) == {"2025-09-03", "2026-03-11"}

    @parameterized.expand([(200, True), (401, False)])
    def test_validate_credentials(self, status_code: int, expected_valid: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = FakeResponse(status_code)
        with mock.patch(f"{NOTION_MODULE}.make_tracked_session", return_value=session):
            valid, _message = self.source.validate_credentials(NotionSourceConfig(api_key="tok"), team_id=1)
        assert valid is expected_valid

    @parameterized.expand(
        [
            (
                "5xx_after_tenacity_exhausted",
                "Notion API error (retryable): status=522, url=https://api.notion.com/v1/comments",
            ),
            (
                "rate_limit_after_tenacity_exhausted",
                "Notion rate limited: url=https://api.notion.com/v1/comments, retry_after=33.0",
            ),
            (
                "ssl_eof_after_tenacity_exhausted",
                "HTTPSConnectionPool(host='api.notion.com', port=443): Max retries exceeded with url: "
                "/v1/blocks/abc123/children?page_size=100 (Caused by SSLError(SSLEOFError(8, "
                "'[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1032)')))",
            ),
            (
                "read_timeout_after_tenacity_exhausted",
                "HTTPSConnectionPool(host='api.notion.com', port=443): Max retries exceeded with url: "
                "/v1/search (Caused by ReadTimeoutError(\"HTTPSConnectionPool(host='api.notion.com', "
                'port=443): Read timed out."))',
            ),
            (
                "non_json_response_after_tenacity_exhausted",
                "Notion returned a non-JSON response: status=200, url=https://api.notion.com/v1/search",
            ),
        ]
    )
    def test_retryable_marker_matches_raised_message(self, _name: str, error_message: str) -> None:
        # notion.py's _request raises the 5xx and rate-limit messages after tenacity's internal
        # retries exhaust, and also lets requests.ConnectionError (which SSLError subclasses) and
        # requests.ReadTimeout through that same retry loop; once the budget exhausts, urllib3
        # wraps them as a "Max retries exceeded with url" message. Matching them all keeps these
        # self-recovering failures out of error tracking as noise instead of being logged as an
        # unclassified exception.
        markers = self.source.get_retryable_errors()
        assert markers
        assert any(marker in error_message for marker in markers)


@pytest.mark.parametrize("status_code", [500, 503])
def test_http_error_message_format_matches_non_retryable(status_code: int) -> None:
    # Sanity check that raised HTTPError messages won't accidentally match the 401/403 patterns.
    mock_response = requests.Response()
    mock_response.status_code = status_code
    mock_response.url = "https://api.notion.com/v1/search"
    with pytest.raises(requests.HTTPError) as exc_info:
        mock_response.raise_for_status()
    non_retryable = NotionSource().get_non_retryable_errors()
    assert not any(pattern in str(exc_info.value) for pattern in non_retryable)
