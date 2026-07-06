import json
import datetime as dt

import pytest
from unittest import mock

import requests
from linkedin_api.common.errors import ResponseFormattingError
from structlog.testing import capture_logs

from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client import (
    LinkedinAdsClient,
    LinkedinAdsDailyRateLimitError,
    LinkedinAdsPivot,
    LinkedinAdsRetryableError,
)


class TestLinkedinAdsClient:
    """Test suite for LinkedinAdsClient."""

    def setup_method(self):
        """Set up test fixtures."""
        self.access_token = "test_access_token"
        self.account_id = "12345"

    def test_init_with_empty_token_raises_error(self):
        """Test client initialization with empty token raises ValueError."""
        with pytest.raises(ValueError, match="Access token required"):
            LinkedinAdsClient("")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_accounts_success(self, mock_restli_client):
        """Test successful accounts retrieval."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.elements = [{"id": "123", "name": "Test Account"}]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)
        result = client.get_accounts()

        assert result == [{"id": "123", "name": "Test Account"}]
        mock_client_instance.finder.assert_called_once()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_accounts_api_error(self, mock_restli_client):
        """Test accounts retrieval with API error."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 401
        mock_response.response.text = "Unauthorized"

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)

        with pytest.raises(Exception, match="LinkedIn API error \\(401\\): Unauthorized"):
            client.get_accounts()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_campaigns_pagination(self, mock_restli_client):
        """Test successful campaigns retrieval with pagination."""
        # First page response
        mock_response1 = mock.MagicMock()
        mock_response1.status_code = 200
        mock_response1.elements = [{"id": "camp1", "name": "Campaign 1"}]
        mock_response1.response.text = json.dumps({"metadata": {"nextPageToken": "token123"}})

        # Second page response
        mock_response2 = mock.MagicMock()
        mock_response2.status_code = 200
        mock_response2.elements = [{"id": "camp2", "name": "Campaign 2"}]
        mock_response2.response.text = json.dumps({"metadata": {}})

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.side_effect = [mock_response1, mock_response2]

        client = LinkedinAdsClient(self.access_token)
        pages = list(client.get_campaigns(self.account_id))

        assert len(pages) == 2
        assert pages[0] == ([{"id": "camp1", "name": "Campaign 1"}], "token123")
        assert pages[1] == ([{"id": "camp2", "name": "Campaign 2"}], None)
        assert mock_client_instance.finder.call_count == 2

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_campaigns_resumes_from_starting_page_token(self, mock_restli_client):
        """Starting page token must be passed as pageToken on the first request."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.elements = [{"id": "camp2", "name": "Campaign 2"}]
        mock_response.response.text = json.dumps({"metadata": {}})

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)
        pages = list(client.get_campaigns(self.account_id, starting_page_token="resume-token-abc"))

        assert len(pages) == 1
        assert pages[0] == ([{"id": "camp2", "name": "Campaign 2"}], None)
        assert mock_client_instance.finder.call_count == 1
        call_params = mock_client_instance.finder.call_args[1]["query_params"]
        assert call_params["pageToken"] == "resume-token-abc"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_creatives_uses_criteria_finder_and_reduced_page_size(self, mock_restli_client):
        """Creatives use `q=criteria` (not `search`) with a reduced pageSize."""
        from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client import (
            CREATIVES_PAGE_SIZE,
        )

        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.elements = [{"id": "urn:li:sponsoredCreative:1", "name": "Creative 1"}]
        mock_response.response.text = json.dumps({"metadata": {}})

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)
        pages = list(client.get_creatives(self.account_id))

        assert len(pages) == 1
        assert pages[0] == ([{"id": "urn:li:sponsoredCreative:1", "name": "Creative 1"}], None)
        assert mock_client_instance.finder.call_count == 1

        call_kwargs = mock_client_instance.finder.call_args[1]
        assert call_kwargs["finder_name"] == "criteria"
        assert call_kwargs["resource_path"] == f"/adAccounts/{self.account_id}/creatives"
        assert call_kwargs["query_params"]["pageSize"] == CREATIVES_PAGE_SIZE

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_analytics_success(self, mock_restli_client):
        """Single weekly chunk yields the API's elements unchanged."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.elements = [
            {
                "impressions": 1000,
                "clicks": 50,
                "costInUsd": 25.50,
                "dateRange": {"start": {"year": 2024, "month": 1, "day": 1}},
            }
        ]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)
        pages = list(
            client.get_analytics(
                account_id=self.account_id,
                pivot=LinkedinAdsPivot.CAMPAIGN,
                date_start="2024-01-01",
                date_end="2024-01-05",
            )
        )

        assert len(pages) == 1
        elements, next_page_token = pages[0]
        assert next_page_token is None
        assert len(elements) == 1
        assert elements[0]["impressions"] == 1000
        assert elements[0]["clicks"] == 50
        assert elements[0]["costInUsd"] == 25.50
        assert mock_client_instance.finder.call_count == 1

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_analytics_uncapped_range_fits_in_single_wide_window(self, mock_restli_client):
        """When responses never cap, even a long range is fetched in a single wide window —
        a small account no longer pays one call per week."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.elements = [{"impressions": 100}]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)
        # 200-day range, well under the 365-day initial window → one call.
        pages = list(
            client.get_analytics(
                account_id=self.account_id,
                pivot=LinkedinAdsPivot.CREATIVE,
                date_start="2024-01-01",
                date_end="2024-07-19",
            )
        )

        assert len(pages) == 1
        assert mock_client_instance.finder.call_count == 1
        assert mock_client_instance.finder.call_args[1]["query_params"]["dateRange"] == {
            "start": {"year": 2024, "month": 1, "day": 1},
            "end": {"year": 2024, "month": 7, "day": 19},
        }

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_analytics_shrinks_window_on_capped_response(self, mock_restli_client):
        """A capped window is discarded and re-fetched at a halved size from the same start;
        the truncated data is never yielded."""
        from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client import (
            ANALYTICS_INITIAL_CHUNK_DAYS,
            ANALYTICS_RESPONSE_CAP,
        )

        calls = 0

        def respond(*args, **kwargs):
            # Only the very first (widest) window caps; every narrower window thereafter fits.
            nonlocal calls
            response = mock.MagicMock()
            response.status_code = 200
            if calls == 0:
                response.elements = [{"impressions": i} for i in range(ANALYTICS_RESPONSE_CAP)]
            else:
                response.elements = [{"impressions": 1}]
            calls += 1
            return response

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.side_effect = respond

        client = LinkedinAdsClient(self.access_token)
        pages = list(
            client.get_analytics(
                account_id=self.account_id,
                pivot=LinkedinAdsPivot.CAMPAIGN,
                date_start="2024-01-01",
                date_end="2025-12-31",
            )
        )

        # The truncated window is never yielded — every yielded page is the fitting (len-1) response.
        assert all(page[0] == [{"impressions": 1}] for page in pages)
        first_window, second_window = (
            call[1]["query_params"]["dateRange"] for call in mock_client_instance.finder.call_args_list[:2]
        )
        # The re-fetch after a cap keeps the same start and halves the span.
        assert first_window["start"] == second_window["start"] == {"year": 2024, "month": 1, "day": 1}
        first_end = dt.date(**{k: first_window["end"][k] for k in ("year", "month", "day")})
        second_end = dt.date(**{k: second_window["end"][k] for k in ("year", "month", "day")})
        assert (first_end - dt.date(2024, 1, 1)).days + 1 == ANALYTICS_INITIAL_CHUNK_DAYS
        assert (second_end - dt.date(2024, 1, 1)).days + 1 == ANALYTICS_INITIAL_CHUNK_DAYS // 2

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_analytics_warns_only_when_single_day_still_caps(self, mock_restli_client):
        """A single-day window that still caps can't be split further, so it yields its partial
        data and logs a warning (the only path that surfaces capped data)."""
        from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client import (
            ANALYTICS_RESPONSE_CAP,
        )

        capped_response = mock.MagicMock()
        capped_response.status_code = 200
        capped_response.elements = [{"impressions": i} for i in range(ANALYTICS_RESPONSE_CAP)]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = capped_response

        client = LinkedinAdsClient(self.access_token)
        # Single-day range → can't shrink below one day.
        # Use structlog's own capture_logs — caplog flattens the event_dict on the
        # way through stdlib so substring matches against `record.message` miss.
        with capture_logs() as logs:
            pages = list(
                client.get_analytics(
                    account_id=self.account_id,
                    pivot=LinkedinAdsPivot.CREATIVE,
                    date_start="2024-01-01",
                    date_end="2024-01-01",
                )
            )

        assert len(pages) == 1
        assert mock_client_instance.finder.call_count == 1
        assert len(pages[0][0]) == ANALYTICS_RESPONSE_CAP
        assert any(log.get("event") == "linkedin_ads.analytics_chunk_capped" for log in logs)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_analytics_same_day_range_makes_one_call(self, mock_restli_client):
        """Same-day range (typical incremental run) → one chunk, one call."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.elements = [{"impressions": 42}]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)
        pages = list(
            client.get_analytics(
                account_id=self.account_id,
                pivot=LinkedinAdsPivot.CAMPAIGN,
                date_start="2024-01-15",
                date_end="2024-01-15",
            )
        )

        assert len(pages) == 1
        assert mock_client_instance.finder.call_count == 1
        date_range = mock_client_instance.finder.call_args[1]["query_params"]["dateRange"]
        assert date_range == {
            "start": {"year": 2024, "month": 1, "day": 15},
            "end": {"year": 2024, "month": 1, "day": 15},
        }

    def test_format_date_range(self):
        """Test date range formatting for LinkedIn API."""
        client = LinkedinAdsClient(self.access_token)
        result = client._format_date_range("2024-01-15", "2024-02-20")

        expected = {"start": {"year": 2024, "month": 1, "day": 15}, "end": {"year": 2024, "month": 2, "day": 20}}
        assert result == expected

    # Retry behavior: tenacity's exponential backoff sleeps are patched out to keep tests instant.

    @pytest.mark.parametrize(
        "transient_factory,expected_calls",
        [
            pytest.param(
                lambda: requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING"),
                3,
                id="ssl_error",
            ),
            pytest.param(
                lambda: requests.exceptions.ConnectionError("RemoteDisconnected"),
                3,
                id="connection_error",
            ),
            pytest.param(
                lambda: requests.exceptions.Timeout("read timed out"),
                3,
                id="timeout",
            ),
            pytest.param(
                lambda: _status_response(504, "Gateway Timeout"),
                2,
                id="http_504",
            ),
            pytest.param(
                lambda: _status_response(500, "Internal Server Error"),
                2,
                id="http_500",
            ),
            pytest.param(
                lambda: _status_response(429, "Too Many Requests"),
                2,
                id="http_429",
            ),
            pytest.param(
                lambda: ResponseFormattingError("Expecting value: line 1 column 1 (char 0)"),
                3,
                id="non_json_response",
            ),
        ],
    )
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_transient_errors_are_retried_then_succeed(
        self, mock_restli_client, _mock_sleep, transient_factory, expected_calls
    ):
        mock_success = mock.MagicMock()
        mock_success.status_code = 200
        mock_success.elements = [{"id": "ok"}]

        transient_failures = [transient_factory() for _ in range(expected_calls - 1)]
        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.side_effect = [*transient_failures, mock_success]

        client = LinkedinAdsClient(self.access_token)
        result = client.get_accounts()

        assert result == [{"id": "ok"}]
        assert mock_client_instance.finder.call_count == expected_calls

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_retries_exhausted_reraises_last_error(self, mock_restli_client, _mock_sleep):
        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.side_effect = requests.exceptions.ConnectionError("boom")

        client = LinkedinAdsClient(self.access_token)

        with pytest.raises(requests.exceptions.ConnectionError, match="boom"):
            client.get_accounts()

        assert mock_client_instance.finder.call_count == 5

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_no_retry_on_4xx(self, mock_restli_client, _mock_sleep):
        mock_response = mock.MagicMock()
        mock_response.status_code = 401
        mock_response.response.text = "Unauthorized"

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)

        with pytest.raises(Exception, match="LinkedIn API error \\(401\\): Unauthorized"):
            client.get_accounts()

        assert mock_client_instance.finder.call_count == 1

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_daily_throttle_429_fails_fast_without_retry(self, mock_restli_client, _mock_sleep):
        """A DAY-window 429 won't reset until midnight UTC, so it raises immediately rather than
        burning the remaining daily call budget on retries."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 429
        mock_response.response.text = (
            "Resource level throttle APPLICATION_AND_MEMBER DAY limit for calls to this resource is reached."
        )

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)

        with pytest.raises(LinkedinAdsDailyRateLimitError, match="daily rate limit reached"):
            client.get_accounts()

        assert mock_client_instance.finder.call_count == 1

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_short_window_429_is_retried(self, mock_restli_client, _mock_sleep):
        """A non-DAY (short-window) 429 stays retryable and eventually succeeds."""
        throttled = mock.MagicMock()
        throttled.status_code = 429
        throttled.response.text = "Resource level throttle APPLICATION_AND_MEMBER MINUTE limit reached."
        throttled.response.headers = {}

        success = mock.MagicMock()
        success.status_code = 200
        success.elements = [{"id": "ok"}]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.side_effect = [throttled, success]

        client = LinkedinAdsClient(self.access_token)
        result = client.get_accounts()

        assert result == [{"id": "ok"}]
        assert mock_client_instance.finder.call_count == 2

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_retry_after_header_is_honoured_and_capped(self, mock_restli_client, mock_tenacity_sleep):
        """A Retry-After header drives the wait (capped at MAX_RETRY_AFTER_SECONDS) instead of the
        default exponential backoff."""
        from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client import (
            MAX_RETRY_AFTER_SECONDS,
        )

        throttled = mock.MagicMock()
        throttled.status_code = 429
        throttled.response.text = "Resource level throttle MINUTE limit reached."
        throttled.response.headers = {"Retry-After": "9999"}

        success = mock.MagicMock()
        success.status_code = 200
        success.elements = [{"id": "ok"}]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.side_effect = [throttled, success]

        client = LinkedinAdsClient(self.access_token)
        result = client.get_accounts()

        assert result == [{"id": "ok"}]
        # tenacity sleeps for the wait our strategy returns — the oversized Retry-After is clamped.
        mock_tenacity_sleep.assert_called_once_with(MAX_RETRY_AFTER_SECONDS)

    @pytest.mark.parametrize("bad_retry_after", ["-1", "-30", "not-a-number"])
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_invalid_retry_after_falls_back_to_backoff(self, mock_restli_client, mock_sleep, bad_retry_after):
        """A negative or non-numeric Retry-After is ignored (never produces a negative sleep that
        would crash tenacity) — we fall back to exponential backoff, which sleeps a positive time."""
        throttled = mock.MagicMock()
        throttled.status_code = 429
        throttled.response.text = "Resource level throttle MINUTE limit reached."
        throttled.response.headers = {"Retry-After": bad_retry_after}

        success = mock.MagicMock()
        success.status_code = 200
        success.elements = [{"id": "ok"}]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.side_effect = [throttled, success]

        client = LinkedinAdsClient(self.access_token)
        result = client.get_accounts()

        assert result == [{"id": "ok"}]
        # Whatever wait we chose, it must be non-negative (tenacity would raise otherwise).
        assert mock_sleep.call_count == 1
        assert mock_sleep.call_args[0][0] >= 0

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_non_json_response_exhausts_retries_as_retryable_error(self, mock_restli_client, _mock_sleep):
        """A persistently non-JSON response is retried, then reraised as LinkedinAdsRetryableError
        rather than crashing the sync with a bare JSONDecodeError from the Restli client."""
        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.side_effect = ResponseFormattingError("Expecting value: line 1 column 1 (char 0)")

        client = LinkedinAdsClient(self.access_token)

        with pytest.raises(LinkedinAdsRetryableError, match="malformed \\(non-JSON\\) response"):
            client.get_accounts()

        assert mock_client_instance.finder.call_count == 5

    def test_retryable_error_is_exported(self):
        assert issubclass(LinkedinAdsRetryableError, Exception)
        assert issubclass(LinkedinAdsDailyRateLimitError, Exception)


def _status_response(status_code: int, text: str) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.response.text = text
    return response
