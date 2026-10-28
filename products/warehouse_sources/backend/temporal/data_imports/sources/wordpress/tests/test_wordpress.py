import ssl
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientNonRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wordpress import (
    WordpressSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress import wordpress as wordpress_module
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.settings import WORDPRESS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.source import WordpressSource
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.wordpress import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    WordpressHostNotAllowedError,
    WordpressResumeConfig,
    WordpressRetryableError,
    _build_initial_params,
    _build_initial_url,
    _format_incremental_value,
    _parse_next_url,
    normalize_host,
    validate_credentials,
)


def _response(
    *,
    status_code: int = 200,
    json_data: Any = None,
    link: Optional[str] = None,
    text: str = "",
    body: Optional[bytes] = None,
) -> ScriptedResponse:
    headers = {"Link": link} if link else {}
    if status_code in (301, 302, 303, 307, 308):
        headers["Location"] = "https://example.com/elsewhere"
    if body is None and json_data is None:
        body = text.encode()
    return ScriptedResponse(status=status_code, json=json_data, headers=headers, body=body)


def _driver(
    site_url: str = "https://example.com", username: str | None = None, application_password: str | None = None
) -> SourceDriver:
    config = WordpressSourceConfig(site_url=site_url, username=username, application_password=application_password)
    return SourceDriver(WordpressSource(), config)


def _ids(result: Any) -> list[Any]:
    return [row_id for table in result.rows for row_id in table.column("id").to_pylist()]


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, ""),
            ("", ""),
            ("example.com", "https://example.com"),
            ("https://example.com", "https://example.com"),
            ("https://example.com/", "https://example.com"),
            ("  blog.example.com  ", "https://blog.example.com"),
            ("https://example.com/wp-json/wp/v2", "https://example.com"),
            ("https://example.com/wp-json", "https://example.com"),
            ("http://example.com:8080/wp-json/wp/v2/", "http://example.com:8080"),
            # Subdirectory installs keep their base path.
            ("https://example.com/blog", "https://example.com/blog"),
            ("https://example.com/blog/wp-json/wp/v2", "https://example.com/blog"),
            # Scheme and host are lower-cased.
            ("HTTPS://Example.COM/", "https://example.com"),
            # Query, fragment, params, or embedded credentials are rejected outright — they could
            # redirect the worker's requests elsewhere on the allowed host (SSRF).
            ("https://example.com/?redirect=internal", ""),
            ("https://example.com/path?x=1", ""),
            ("https://example.com/#frag", ""),
            ("https://example.com/path;params", ""),
            ("https://user:pass@example.com/", ""),
            ("https://attacker@example.com/", ""),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            # WordPress compares against the site-local datetime; we emit wall-clock with no tz conversion.
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            (date(2026, 3, 4), "2026-03-04T00:00:00"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected


class TestBuildInitialParams:
    def test_comments_incremental_uses_after_only(self):
        params = _build_initial_params(
            WORDPRESS_ENDPOINTS["comments"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, 12, 0, 0),
            incremental_field="date",
        )
        assert params["after"] == "2024-01-01T10:00:00"
        assert params["orderby"] == "date"

    def test_comments_reject_modified_incremental_field(self):
        # Comments silently ignore modified_after, so it isn't an advertised cursor and must raise.
        with pytest.raises(ValueError):
            _build_initial_params(
                WORDPRESS_ENDPOINTS["comments"],
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 1),
                incremental_field="modified",
            )


class TestBuildInitialUrl:
    def test_accepts_bare_hostname(self):
        url = _build_initial_url("example.com", WORDPRESS_ENDPOINTS["users"], {})
        assert url == "https://example.com/wp-json/wp/v2/users"


class TestParseNextUrl:
    @pytest.mark.parametrize(
        "header, expected",
        [
            ("", None),
            ('<https://example.com/wp-json/wp/v2/posts?page=1>; rel="prev"', None),
            (
                '<https://example.com/wp-json/wp/v2/posts?page=2>; rel="next"',
                "https://example.com/wp-json/wp/v2/posts?page=2",
            ),
        ],
    )
    def test_parse(self, header, expected):
        assert _parse_next_url(header) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_msg_substr",
        [
            (404, False, "REST API not found"),
        ],
    )
    def test_status_code_mapping(self, status_code, expected_valid, expected_msg_substr):
        with scripted_network(always(_response(status_code=status_code, json_data=[]))):
            valid, msg = validate_credentials("https://example.com", None, None)
            assert valid is expected_valid
            if expected_msg_substr is None:
                assert msg is None
            else:
                assert expected_msg_substr in (msg or "")

    @pytest.mark.parametrize(
        "json_data, text, expects_substr, forbidden_substr",
        [
            # A bare proxy/WAF status line must not leak; the user gets an actionable message instead.
            (None, "Bad Request", "unexpected response (HTTP 400)", "Bad Request"),
            # A genuine WordPress REST error message is still surfaced.
            ({"message": "rest_invalid_param"}, "", "rest_invalid_param", None),
        ],
    )
    def test_unrecognized_status_does_not_leak_raw_body(self, json_data, text, expects_substr, forbidden_substr):
        with scripted_network(always(_response(status_code=400, json_data=json_data, text=text))):
            valid, msg = validate_credentials("https://example.com", None, None)
            assert valid is False
            assert expects_substr in (msg or "")
            if forbidden_substr is not None:
                assert forbidden_substr not in (msg or "")

    def test_invalid_site_url(self):
        valid, msg = validate_credentials("", None, None)
        assert valid is False
        assert msg == "Invalid WordPress site URL"

    @pytest.mark.parametrize(
        "exc_factory, expected_msg_substr",
        [
            (lambda: ssl.SSLError("certificate verify failed"), "secure connection"),
            (lambda: ConnectionResetError("boom"), "Couldn't connect"),
        ],
    )
    def test_request_exception_returns_actionable_message(self, exc_factory, expected_msg_substr):
        # The raw exception string (e.g. an SSL traceback) must never surface to the user.
        with scripted_network(always(exc_factory())):
            valid, msg = validate_credentials("https://example.com", None, None)
            assert valid is False
            assert expected_msg_substr in (msg or "")
            assert "certificate verify failed" not in (msg or "")

    @pytest.mark.parametrize(
        "exc_factory, expected_msg_substr",
        [
            (lambda: requests.exceptions.Timeout("slow"), "took too long"),
            (lambda: requests.exceptions.RequestException("weird"), "Couldn't reach"),
        ],
    )
    def test_request_exception_the_socket_cannot_raise_returns_actionable_message(
        self, exc_factory, expected_msg_substr
    ):
        # The scripted network surfaces every transport failure as a connection error, so these two
        # exception classes can only be raised by the session itself.
        session = mock.MagicMock()
        session.get.side_effect = exc_factory()
        with mock.patch.object(wordpress_module, "make_tracked_session", return_value=session):
            valid, msg = validate_credentials("https://example.com", None, None)
        assert valid is False
        assert expected_msg_substr in (msg or "")

    def test_rejects_redirect_response(self):
        with scripted_network([_response(status_code=302)]) as network:
            valid, msg = validate_credentials("https://example.com", None, None)

        assert valid is False
        assert msg == HOST_NOT_ALLOWED_ERROR
        assert len(network.requests_log) == 1

    def test_rejects_plaintext_http_when_credentials_present(self):
        # Basic-auth credentials must never be sent over plaintext HTTP.
        with scripted_network([_response(json_data=[])]) as network:
            valid, msg = validate_credentials("http://example.com", "admin", "app pass word")

        assert valid is False
        assert msg == HTTP_NOT_ALLOWED_ERROR
        assert network.requests_log == []

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(wordpress_module, "_is_host_safe", return_value=(False, "internal address")),
            scripted_network([_response(json_data=[])]) as network,
        ):
            valid, msg = validate_credentials("https://10.0.0.1", None, None, team_id=99)

        assert valid is False
        assert msg == "internal address"
        assert network.requests_log == []


class TestWordpressSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, partition_key",
        [
            ("posts", "date"),
            ("pages", "date"),
            ("comments", "date"),
            ("media", "date"),
            ("categories", None),
            ("tags", None),
            ("users", None),
        ],
    )
    def test_response_shape(self, endpoint, partition_key):
        result = _driver().run(endpoint, always(_response(json_data=[])))

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestGetRows:
    def test_follows_link_header_across_pages(self):
        page1 = _response(
            json_data=[{"id": 1}, {"id": 2}],
            link='<https://example.com/wp-json/wp/v2/posts?page=2>; rel="next"',
        )
        page2 = _response(json_data=[{"id": 3}])
        result = _driver().run("posts", [page1, page2])

        assert _ids(result) == [1, 2, 3]
        assert result.urls[1] == "https://example.com/wp-json/wp/v2/posts?page=2"

    def test_resumes_from_saved_state(self):
        result = _driver().run(
            "posts",
            [_response(json_data=[{"id": 9}])],
            resume_state=WordpressResumeConfig(next_url="https://example.com/wp-json/wp/v2/posts?page=5"),
        )

        assert result.urls[0] == "https://example.com/wp-json/wp/v2/posts?page=5"
        assert _ids(result) == [9]

    def test_checkpoints_the_current_page_url_when_a_chunk_is_yielded(self):
        first_url = "https://example.com/wp-json/wp/v2/posts?per_page=100"
        next_url = "https://example.com/wp-json/wp/v2/posts?page=2"
        full_chunk = [{"id": i} for i in range(2000)]
        page1 = _response(json_data=full_chunk, link=f'<{next_url}>; rel="next"')
        page2 = _response(json_data=[{"id": 2000}])

        result = _driver().run("posts", [page1, page2])

        assert len(_ids(result)) == 2001
        assert result.saved_states
        assert result.saved_states[0] == WordpressResumeConfig(next_url=result.urls[0])
        assert result.urls[0] != next_url
        assert first_url.split("?")[0] == result.urls[0].split("?")[0]

    def test_empty_body_terminates_without_crashing(self):
        # A 2xx with an empty body used to crash get_rows with a raw JSONDecodeError; it must now
        # stop pagination cleanly.
        result = _driver().run("posts", [_response(body=b"")])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1

    def test_non_json_body_is_non_retryable(self):
        # A 2xx serving an HTML error/login page can't become data by retrying — fail fast and
        # non-retryably, without leaking the query string into the surfaced message.
        html = _response(body=b"<!DOCTYPE html><html><body>Login</body></html>")

        result = _driver().run("posts", [html])

        assert isinstance(result.raised, RESTClientNonRetryableError)
        assert str(result.raised).startswith("Non-JSON response from")
        assert "per_page" not in str(result.raised)

    def test_truncated_json_body_stays_retryable(self):
        # A body that begins as JSON but fails to parse is a truncated read, not a non-JSON error
        # page, so it must stay retryable rather than being classified non-retryable.
        truncated = _response(body=b'[{"id": 1}')

        result = _driver().run("posts", always(truncated))

        assert isinstance(result.raised, WordpressRetryableError)

    def test_does_not_follow_next_url_on_foreign_host(self):
        page1 = _response(
            json_data=[{"id": 1}],
            link='<http://169.254.169.254/latest/meta-data/>; rel="next"',
        )

        result = _driver().run("posts", [page1])

        assert _ids(result) == [1]
        assert len(result.requests) == 1

    def test_ignores_resume_url_on_foreign_host(self):
        result = _driver().run(
            "posts",
            [_response(json_data=[{"id": 1}])],
            resume_state=WordpressResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"),
        )

        assert result.urls[0].startswith("https://example.com/wp-json/wp/v2/posts")
        assert _ids(result) == [1]

    def test_raises_on_redirect(self):
        result = _driver().run("posts", [_response(status_code=302)])

        assert isinstance(result.raised, WordpressHostNotAllowedError)
        assert HOST_NOT_ALLOWED_ERROR in str(result.raised)

    def test_unsafe_host_error_is_marked_non_retryable(self):
        with mock.patch.object(wordpress_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver().run("posts", [_response(json_data=[{"id": 1}])])

        assert isinstance(result.raised, WordpressHostNotAllowedError)
        assert HOST_NOT_ALLOWED_ERROR in str(result.raised)

    def test_rejects_plaintext_http_with_credentials_before_request(self):
        result = _driver("http://example.com", "admin", "app pass word").run(
            "posts", [_response(json_data=[{"id": 1}])]
        )

        assert isinstance(result.raised, WordpressHostNotAllowedError)
        assert HTTP_NOT_ALLOWED_ERROR in str(result.raised)
        assert result.requests == []

    def test_passes_allow_redirects_false(self):
        # A redirect is surfaced as an error instead of being followed to the Location target.
        result = _driver().run("posts", [_response(status_code=302)])

        assert len(result.requests) == 1
        assert result.requests[0].url.startswith("https://example.com/wp-json/wp/v2/posts")


class TestRetryAfter:
    @pytest.mark.parametrize(
        "header, expected",
        [
            ({"Retry-After": "5"}, 5.0),
            ({"Retry-After": "  9 "}, 9.0),
            ({"Retry-After": "100000"}, 60.0),  # capped
            ({"Retry-After": "Wed, 21 Oct 2025 07:28:00 GMT"}, None),  # HTTP-date ignored
            ({}, None),
        ],
    )
    def test_parse_retry_after(self, header, expected):
        from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.wordpress import (
            _parse_retry_after,
        )

        response = mock.MagicMock()
        response.headers = header
        assert _parse_retry_after(response) == expected

    def test_retry_wait_prefers_retry_after(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.wordpress import (
            WordpressRetryableError,
            _retry_wait,
        )

        state = mock.MagicMock()
        state.outcome.exception.return_value = WordpressRetryableError("rate limited", retry_after=7.0)
        assert _retry_wait(state) == 7.0
