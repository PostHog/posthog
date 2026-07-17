import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.google_pagespeed_insights.google_pagespeed_insights import (
    CATEGORIES,
    MAX_URLS,
    PAGESPEED_BASE_URL,
    PageSpeedRetryableError,
    _analysis_timestamp_to_iso,
    _build_url,
    _fetch,
    _normalize_row,
    _redact_key,
    get_rows,
    google_pagespeed_insights_source,
    parse_urls,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_pagespeed_insights.settings import (
    PAGESPEED_ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.google_pagespeed_insights.google_pagespeed_insights"


def _response(status: int = 200, body: Optional[dict[str, Any]] = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    if not resp.ok:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error for url: {PAGESPEED_BASE_URL}", response=requests.Response()
        )
    return resp


class TestParseUrls:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://posthog.com", ["https://posthog.com"]),
            ("  https://posthog.com  ", ["https://posthog.com"]),
            ("https://posthog.com\nhttps://posthog.com/docs", ["https://posthog.com", "https://posthog.com/docs"]),
            ("https://a.com\n\n  \nhttp://b.com", ["https://a.com", "http://b.com"]),
            # Duplicates are dropped (order preserved) so one URL can't seed two rows with the same key.
            ("https://a.com\nhttps://a.com", ["https://a.com"]),
        ],
    )
    def test_valid(self, raw, expected):
        assert parse_urls(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [None, "", "   \n  ", "posthog.com", "ftp://posthog.com", "not a url", "://missing-scheme"],
    )
    def test_invalid_raises(self, raw):
        with pytest.raises(ValueError):
            parse_urls(raw)

    @pytest.mark.parametrize(
        "raw",
        [
            "http://localhost",
            "http://127.0.0.1",
            "http://10.0.0.1",
            "http://192.168.1.1",
            # Cloud metadata endpoint (link-local) — the classic SSRF target.
            "http://169.254.169.254",
            "http://[::1]",
            "https://service.internal",
            "https://printer.local",
        ],
    )
    def test_rejects_private_hosts(self, raw):
        # Defense-in-depth: private / loopback / internal hosts are rejected up front rather than
        # handed to the connector, even though the actual fetch runs on Google's servers.
        with pytest.raises(ValueError, match="cannot be analyzed"):
            parse_urls(raw)

    def test_rejects_too_many_urls(self):
        raw = "\n".join(f"https://example.com/{i}" for i in range(MAX_URLS + 1))
        with pytest.raises(ValueError, match="Too many URLs"):
            parse_urls(raw)

    def test_allows_max_urls(self):
        raw = "\n".join(f"https://example.com/{i}" for i in range(MAX_URLS))
        assert len(parse_urls(raw)) == MAX_URLS


class TestBuildUrl:
    def test_includes_url_strategy_key_and_repeated_categories(self):
        url = _build_url("https://posthog.com", "MOBILE", "secret-key")

        assert url.startswith(f"{PAGESPEED_BASE_URL}?")
        assert "strategy=MOBILE" in url
        assert "key=secret-key" in url
        # The URL value is percent-encoded (Google expects it), so the raw scheme separator is escaped.
        assert "url=https%3A%2F%2Fposthog.com" in url
        # `category` is repeatable — one param per requested Lighthouse category.
        assert url.count("category=") == len(CATEGORIES)


class TestRedactKey:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("https://x/runPagespeed?key=secret", "https://x/runPagespeed?key=REDACTED"),
            (
                "https://x/runPagespeed?url=a&key=secret&strategy=DESKTOP",
                "https://x/runPagespeed?url=a&key=REDACTED&strategy=DESKTOP",
            ),
            # A field that merely contains "key" must not be redacted — only the `key` query param.
            ("https://x/runPagespeed?pageToken=abc", "https://x/runPagespeed?pageToken=abc"),
            ("no key here", "no key here"),
        ],
    )
    def test_redact(self, text, expected):
        assert _redact_key(text) == expected


class TestAnalysisTimestampToIso:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2024-01-15T12:34:56.789Z", "2024-01-15T12:34:56.789000+00:00"),
            ("2024-01-15T12:34:56Z", "2024-01-15T12:34:56+00:00"),
            # A non-UTC offset is normalized back to UTC.
            ("2024-01-15T14:34:56+02:00", "2024-01-15T12:34:56+00:00"),
            (None, None),
            ("", None),
            ("garbage", None),
            (12345, None),
        ],
    )
    def test_parse(self, value, expected):
        assert _analysis_timestamp_to_iso(value) == expected


class TestNormalizeRow:
    def test_injects_requested_url_strategy_and_timestamp(self):
        response = {
            "analysisUTCTimestamp": "2024-01-15T12:34:56Z",
            "id": "https://posthog.com/",
            "lighthouseResult": {},
        }
        row = _normalize_row(PAGESPEED_ENDPOINTS["pagespeed_desktop"], response, "https://posthog.com")

        assert row is not None
        # The requested URL (not the echoed final `id`) is injected so the primary key stays stable.
        assert row["requested_url"] == "https://posthog.com"
        assert row["strategy"] == "DESKTOP"
        assert row["analysis_timestamp"] == "2024-01-15T12:34:56+00:00"
        # The raw response fields are preserved alongside the injected columns.
        assert row["id"] == "https://posthog.com/"

    def test_mobile_endpoint_stamps_mobile_strategy(self):
        response = {"analysisUTCTimestamp": "2024-01-15T12:34:56Z"}
        row = _normalize_row(PAGESPEED_ENDPOINTS["pagespeed_mobile"], response, "https://posthog.com")

        assert row is not None
        assert row["strategy"] == "MOBILE"

    def test_unparseable_timestamp_returns_none(self):
        # analysis_timestamp is part of the primary/partition key; a present-but-unparseable timestamp
        # must not flow a null key into the merge.
        response = {"analysisUTCTimestamp": "not-a-timestamp"}
        assert _normalize_row(PAGESPEED_ENDPOINTS["pagespeed_desktop"], response, "https://posthog.com") is None

    def test_missing_timestamp_field_raises(self):
        # A missing timestamp field signals a structural API change and must fail loudly rather than
        # silently dropping every row and reporting a successful zero-row sync.
        with pytest.raises(KeyError):
            _normalize_row(PAGESPEED_ENDPOINTS["pagespeed_desktop"], {"lighthouseResult": {}}, "https://posthog.com")


# tenacity exposes the undecorated function via `__wrapped__`, so status classification can be
# asserted without waiting through retry backoff.
_fetch_once = _fetch.__wrapped__  # type: ignore[attr-defined]


class TestFetch:
    def test_success_returns_json(self):
        session = mock.MagicMock()
        session.get.return_value = _response(200, {"analysisUTCTimestamp": "2024-01-15T12:34:56Z"})

        body = _fetch_once(session, "k", "DESKTOP", "https://posthog.com", structlog.get_logger())

        assert body == {"analysisUTCTimestamp": "2024-01-15T12:34:56Z"}
        session.get.assert_called_once()

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable(self, status):
        session = mock.MagicMock()
        session.get.return_value = _response(status)

        with pytest.raises(PageSpeedRetryableError):
            _fetch_once(session, "k", "DESKTOP", "https://posthog.com", structlog.get_logger())

    @pytest.mark.parametrize("status", [400, 403, 404])
    def test_client_error_raises_for_status(self, status):
        session = mock.MagicMock()
        session.get.return_value = _response(status)

        with pytest.raises(requests.HTTPError):
            _fetch_once(session, "k", "DESKTOP", "https://posthog.com", structlog.get_logger())

    def test_error_message_redacts_key(self):
        resp = mock.MagicMock()
        resp.status_code = 400
        resp.ok = False
        resp.text = '{"error":{"message":"API key not valid."}}'
        resp.raise_for_status.side_effect = requests.HTTPError(
            "400 Client Error: Bad Request for url: "
            "https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed?url=https://x&key=SUPERSECRETKEY",
            response=requests.Response(),
        )
        session = mock.MagicMock()
        session.get.return_value = resp

        with pytest.raises(requests.HTTPError) as exc_info:
            _fetch_once(session, "k", "DESKTOP", "https://posthog.com", structlog.get_logger())

        message = str(exc_info.value)
        assert "SUPERSECRETKEY" not in message
        assert "key=REDACTED" in message
        # The host prefix is preserved so non-retryable-error matching still works.
        assert "for url: https://pagespeedonline.googleapis.com" in message

    def test_chunked_encoding_error_is_retried(self):
        # A connection broken mid-response surfaces as ChunkedEncodingError, which isn't a subclass of
        # ConnectionError — it must still be retried rather than failing the sync on the first hiccup.
        session = mock.MagicMock()
        session.get.side_effect = [
            requests.exceptions.ChunkedEncodingError(
                "Connection broken: InvalidChunkLength(got length b'', 0 bytes read)"
            ),
            _response(200, {"analysisUTCTimestamp": "2024-01-15T12:34:56Z"}),
        ]

        with mock.patch.object(_fetch.retry, "sleep"):
            body = _fetch(session, "k", "DESKTOP", "https://posthog.com", structlog.get_logger())

        assert body == {"analysisUTCTimestamp": "2024-01-15T12:34:56Z"}
        assert session.get.call_count == 2

    @pytest.mark.parametrize("exc_type", [requests.ConnectionError, requests.ReadTimeout, requests.exceptions.SSLError])
    def test_transport_error_redacts_key_and_preserves_type(self, exc_type):
        # Transport failures (no HTTP response) embed the full request URL, including `key=...`, in
        # their message. They must be re-raised redacted and with their original type so the key never
        # reaches `latest_error` and retry classification is unchanged.
        session = mock.MagicMock()
        session.get.side_effect = exc_type(
            "HTTPSConnectionPool(host='pagespeedonline.googleapis.com'): "
            "url: /pagespeedonline/v5/runPagespeed?url=https://x&key=SUPERSECRETKEY"
        )

        with pytest.raises(exc_type) as exc_info:
            _fetch_once(session, "k", "DESKTOP", "https://posthog.com", structlog.get_logger())

        message = str(exc_info.value)
        assert "SUPERSECRETKEY" not in message
        assert "key=REDACTED" in message


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [(200, True), (400, False), (403, False), (500, False)],
    )
    def test_status_mapping(self, status, expected_valid):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status)

            is_valid, _ = validate_credentials("test-key", "https://posthog.com")

        assert is_valid is expected_valid

    def test_malformed_urls_is_invalid_without_request(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            is_valid, message = validate_credentials("test-key", "not-a-url")

        assert is_valid is False
        assert message is not None
        mock_session.return_value.get.assert_not_called()

    def test_network_error_is_invalid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("test-key", "https://posthog.com")

        assert is_valid is False
        assert message is not None

    def test_probes_first_url(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200)

            validate_credentials("test-key", "https://posthog.com\nhttps://example.com")

            called_url = mock_session.return_value.get.call_args[0][0]

        assert "url=https%3A%2F%2Fposthog.com" in called_url


class TestGetRows:
    def test_yields_one_batch_per_url_and_targets_each(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, {"analysisUTCTimestamp": "2024-01-15T12:00:00Z"}),
                _response(200, {"analysisUTCTimestamp": "2024-01-15T12:00:01Z"}),
            ]

            batches = list(
                get_rows("test-key", "pagespeed_desktop", ["https://a.com", "https://b.com"], structlog.get_logger())
            )

        assert len(batches) == 2
        assert batches[0][0]["requested_url"] == "https://a.com"
        assert batches[1][0]["requested_url"] == "https://b.com"
        assert all(batch[0]["strategy"] == "DESKTOP" for batch in batches)

    def test_targets_requested_strategy(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(
                200, {"analysisUTCTimestamp": "2024-01-15T12:00:00Z"}
            )

            list(get_rows("test-key", "pagespeed_mobile", ["https://a.com"], structlog.get_logger()))

            called_url = mock_session.return_value.get.call_args[0][0]

        assert "strategy=MOBILE" in called_url

    def test_skips_rows_with_unparseable_timestamp(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, {"analysisUTCTimestamp": "garbage"})

            batches = list(get_rows("test-key", "pagespeed_desktop", ["https://a.com"], structlog.get_logger()))

        assert batches == []


class TestSource:
    @pytest.mark.parametrize("endpoint", list(PAGESPEED_ENDPOINTS))
    def test_source_response_shape(self, endpoint):
        response = google_pagespeed_insights_source("test-key", endpoint, "https://posthog.com", structlog.get_logger())

        assert response.name == endpoint
        assert response.primary_keys == ["requested_url", "analysis_timestamp"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["analysis_timestamp"]
        assert response.sort_mode == "asc"

    def test_invalid_urls_raise(self):
        with pytest.raises(ValueError):
            google_pagespeed_insights_source("test-key", "pagespeed_desktop", "garbage", structlog.get_logger())
