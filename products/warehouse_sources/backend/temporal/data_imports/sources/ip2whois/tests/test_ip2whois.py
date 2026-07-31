import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.ip2whois.ip2whois import (
    IP2WHOIS_BASE_URL,
    MAX_DOMAINS,
    IP2WhoisAPIError,
    IP2WhoisRetryableError,
    _fetch_domain,
    get_rows,
    ip2whois_source,
    normalize_domain,
    parse_domains,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.ip2whois.ip2whois"


def _response(status: int = 200, body: Optional[dict[str, Any]] = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden"}.get(status, "")
    resp.json.return_value = body if body is not None else {}
    resp.text = json.dumps(body if body is not None else {})
    return resp


class TestNormalizeDomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("example.com", "example.com"),
            ("  Example.COM  ", "example.com"),
            ("www.example.com", "example.com"),
            ("https://www.posthog.com/pricing?x=1", "posthog.com"),
            ("http://foo.bar.baz:8080/path", "foo.bar.baz"),
            ("a.co", "a.co"),
            # Unusable tokens normalize to None so the caller skips them (no wasted lookup).
            ("", None),
            ("   ", None),
            ("not a domain", None),
            ("localhost", None),
            ("just-text", None),
            ("http://", None),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_domain(raw) == expected


class TestParseDomains:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("example.com", ["example.com"]),
            ("example.com\nposthog.com", ["example.com", "posthog.com"]),
            ("example.com, posthog.com", ["example.com", "posthog.com"]),
            ("example.com posthog.com", ["example.com", "posthog.com"]),
            # Dedup is case/host normalized and order-preserving.
            ("example.com\nEXAMPLE.com\nwww.example.com", ["example.com"]),
            # Invalid tokens are dropped, valid ones kept.
            ("example.com\ngarbage\nposthog.com", ["example.com", "posthog.com"]),
        ],
    )
    def test_valid(self, raw, expected):
        assert parse_domains(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   \n  ", "garbage", "not a domain\nlocalhost"])
    def test_invalid_raises(self, raw):
        with pytest.raises(ValueError):
            parse_domains(raw)

    def test_rejects_too_many_domains(self):
        raw = "\n".join(f"domain{i}.com" for i in range(MAX_DOMAINS + 1))
        with pytest.raises(ValueError, match="Too many domains"):
            parse_domains(raw)


# tenacity exposes the undecorated function via `__wrapped__`, so status classification can be
# asserted without waiting through retry backoff.
_fetch_once = _fetch_domain.__wrapped__  # type: ignore[attr-defined]


class TestFetchDomain:
    def test_success_injects_queried_domain(self):
        session = mock.MagicMock()
        # The API echoes an upper-cased domain; the queried (normalized) value must win as the key.
        session.get.return_value = _response(200, {"domain": "EXAMPLE.COM", "create_date": "1997-09-15T04:00:00Z"})

        row = _fetch_once(session, "secret", "example.com", structlog.get_logger())

        assert row is not None
        assert row["domain"] == "example.com"
        assert row["create_date"] == "1997-09-15T04:00:00Z"

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable(self, status):
        session = mock.MagicMock()
        session.get.return_value = _response(status)

        with pytest.raises(IP2WhoisRetryableError):
            _fetch_once(session, "secret", "example.com", structlog.get_logger())

    @pytest.mark.parametrize("status, reason", [(401, "Unauthorized"), (403, "Forbidden")])
    def test_auth_errors_raise_http_error_without_key(self, status, reason):
        session = mock.MagicMock()
        session.get.return_value = _response(
            status, {"error": {"error_code": 10001, "error_message": "API key not found."}}
        )

        with pytest.raises(requests.HTTPError) as exc_info:
            _fetch_once(session, "SUPERSECRETKEY", "example.com", structlog.get_logger())

        message = str(exc_info.value)
        # The key must never reach the raised error, but the host prefix that
        # get_non_retryable_errors matches on must be preserved.
        assert "SUPERSECRETKEY" not in message
        assert f"{status} Client Error: {reason} for url: {IP2WHOIS_BASE_URL}" == message

    def test_domain_level_error_is_skipped(self):
        # A per-domain rejection (HTTP 400, code 10007) must skip just this domain, not fail the sync.
        session = mock.MagicMock()
        session.get.return_value = _response(400, {"error": {"error_code": 10007, "error_message": "Invalid domain."}})

        assert _fetch_once(session, "secret", "bad_domain.invalid", structlog.get_logger()) is None

    def test_account_level_error_raises(self):
        # A 200 body-level error that isn't a domain-level code (e.g. quota) is fatal for the run.
        session = mock.MagicMock()
        session.get.return_value = _response(
            200, {"error": {"error_code": 10002, "error_message": "Insufficient query."}}
        )

        with pytest.raises(IP2WhoisAPIError, match=r"\[10002\]"):
            _fetch_once(session, "secret", "example.com", structlog.get_logger())

    def test_account_error_mentioning_domain_still_raises(self):
        # Classification is by error code, not message text: an account/quota error whose message
        # happens to contain "domain" must NOT be mistaken for a per-domain skip (which would silently
        # empty a full-refresh table). Only codes in the allow-list skip.
        session = mock.MagicMock()
        session.get.return_value = _response(
            200, {"error": {"error_code": 10004, "error_message": "Domain lookup quota exceeded."}}
        )

        with pytest.raises(IP2WhoisAPIError, match=r"\[10004\]"):
            _fetch_once(session, "secret", "example.com", structlog.get_logger())

    def test_unexpected_non_ok_without_envelope_raises(self):
        # A non-2xx with no error envelope can't be attributed to this domain, so fail loudly rather
        # than silently dropping the row.
        session = mock.MagicMock()
        session.get.return_value = _response(404, {})

        with pytest.raises(IP2WhoisAPIError):
            _fetch_once(session, "secret", "example.com", structlog.get_logger())


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, body, expected_valid",
        [
            (200, {"domain": "example.com"}, True),
            # 400 means the probe domain was rejected but the key was accepted.
            (400, {"error": {"error_code": 10007, "error_message": "Invalid domain."}}, True),
            (401, {"error": {"error_code": 10001, "error_message": "API key not found."}}, False),
            (403, {"error": {"error_code": 10001, "error_message": "API key not found."}}, False),
            # A 200 body-level key error is still an invalid key.
            (200, {"error": {"error_code": 10001, "error_message": "Invalid API key."}}, False),
        ],
    )
    def test_status_mapping(self, status, body, expected_valid):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status, body)

            is_valid, _ = validate_credentials("test-key", "example.com")

        assert is_valid is expected_valid

    def test_malformed_domains_is_invalid_without_request(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            is_valid, message = validate_credentials("test-key", "garbage")

        assert is_valid is False
        assert message is not None
        mock_session.return_value.get.assert_not_called()

    def test_network_error_is_invalid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("test-key", "example.com")

        assert is_valid is False
        assert message is not None

    def test_probes_first_domain(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, {"domain": "example.com"})

            validate_credentials("test-key", "example.com\nposthog.com")

            called_url = mock_session.return_value.get.call_args[0][0]

        assert called_url.startswith(IP2WHOIS_BASE_URL)
        assert "domain=example.com" in called_url


class TestGetRows:
    def test_yields_one_batch_per_domain_and_targets_each(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, {"domain": "EXAMPLE.COM"}),
                _response(200, {"domain": "posthog.com"}),
            ]

            batches = list(get_rows("test-key", ["example.com", "posthog.com"], structlog.get_logger()))

        assert [batch[0]["domain"] for batch in batches] == ["example.com", "posthog.com"]

    def test_skips_domains_that_return_none(self):
        # A domain-level rejection drops out; the rest of the list still syncs.
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(400, {"error": {"error_code": 10007, "error_message": "Invalid domain."}}),
                _response(200, {"domain": "posthog.com"}),
            ]

            batches = list(get_rows("test-key", ["bad.invalid", "posthog.com"], structlog.get_logger()))

        assert [batch[0]["domain"] for batch in batches] == ["posthog.com"]

    def test_all_domains_skipped_raises_rather_than_emptying_table(self):
        # Full refresh replaces the table with this run's rows. If every domain is skipped we must fail
        # loudly, not complete "successfully" with an empty table.
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(
                400, {"error": {"error_code": 10007, "error_message": "Invalid domain."}}
            )

            with pytest.raises(IP2WhoisAPIError, match="no WHOIS data"):
                list(get_rows("test-key", ["bad1.invalid", "bad2.invalid"], structlog.get_logger()))


class TestIP2WhoisSource:
    def test_source_response_shape(self):
        response = ip2whois_source("test-key", "whois", "example.com", structlog.get_logger())

        assert response.name == "whois"
        assert response.primary_keys == ["domain"]
        assert response.sort_mode == "asc"
        # WHOIS is a current-state lookup, so no partitioning.
        assert response.partition_mode is None

    def test_invalid_domains_raise(self):
        with pytest.raises(ValueError):
            ip2whois_source("test-key", "whois", "garbage", structlog.get_logger())
