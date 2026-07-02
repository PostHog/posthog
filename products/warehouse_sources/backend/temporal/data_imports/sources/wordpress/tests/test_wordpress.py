from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress import wordpress as wordpress_module
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.settings import WORDPRESS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.wordpress import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    WordpressHostNotAllowedError,
    WordpressResumeConfig,
    _build_initial_params,
    _build_initial_url,
    _format_incremental_value,
    _get_headers,
    _is_same_host,
    _parse_next_url,
    get_rows,
    normalize_host,
    validate_credentials,
    wordpress_source,
)


def _response(
    *, status_code: int = 200, json_data: Any = None, link: Optional[str] = None, text: str = ""
) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (301, 302, 303, 307, 308)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    response.headers = {"Link": link} if link else {}
    return response


class _FakeBatcher:
    """Yields whatever is buffered on every ``should_yield`` check, so the per-item save_state path
    in ``get_rows`` is exercised without needing thousands of rows."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._buf: list[Any] = []

    def batch(self, item: Any) -> None:
        self._buf.append(item)

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return len(self._buf) > 0

    def get_table(self) -> list[Any]:
        rows, self._buf = self._buf, []
        return rows


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


class TestGetHeaders:
    def test_anonymous_has_no_authorization(self):
        headers = _get_headers(None, None)
        assert "Authorization" not in headers
        assert headers["Accept"] == "application/json"

    def test_partial_credentials_are_anonymous(self):
        # A username without a password (or vice versa) is not enough to authenticate.
        assert "Authorization" not in _get_headers("admin", "")
        assert "Authorization" not in _get_headers("", "secret")

    def test_basic_auth_header_is_base64_of_user_colon_password(self):
        import base64

        headers = _get_headers("admin", "abcd efgh")
        expected = base64.b64encode(b"admin:abcd efgh").decode()
        assert headers["Authorization"] == f"Basic {expected}"


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

    def test_no_z_or_offset_suffix(self):
        result = _format_incremental_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert "+00:00" not in result and not result.endswith("Z")


class TestBuildInitialParams:
    def test_posts_incremental_modified_uses_modified_after(self):
        params = _build_initial_params(
            WORDPRESS_ENDPOINTS["posts"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, 12, 0, 0),
            incremental_field="modified",
        )
        # 2-hour lookback applied before formatting.
        assert params["modified_after"] == "2024-01-01T10:00:00"
        assert params["orderby"] == "modified"
        assert params["order"] == "asc"
        assert params["per_page"] == 100

    def test_posts_incremental_date_uses_after(self):
        params = _build_initial_params(
            WORDPRESS_ENDPOINTS["posts"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, 12, 0, 0),
            incremental_field="date",
        )
        assert params["after"] == "2024-01-01T10:00:00"
        assert "modified_after" not in params
        assert params["orderby"] == "date"

    def test_posts_full_refresh_uses_stable_order_by(self):
        params = _build_initial_params(
            WORDPRESS_ENDPOINTS["posts"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 1, 1),
            incremental_field=None,
        )
        assert "after" not in params and "modified_after" not in params
        assert params["orderby"] == "date"
        assert params["order"] == "asc"

    def test_incremental_without_watermark_has_no_filter(self):
        params = _build_initial_params(
            WORDPRESS_ENDPOINTS["posts"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="modified",
        )
        assert "modified_after" not in params
        assert params["orderby"] == "date"  # stable order on the first sync

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

    @pytest.mark.parametrize("endpoint", ["categories", "tags", "users"])
    def test_full_refresh_endpoints_only_order_by_id(self, endpoint):
        params = _build_initial_params(
            WORDPRESS_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1),
            incremental_field=None,
        )
        assert "after" not in params and "modified_after" not in params
        assert params["orderby"] == "id"


class TestBuildInitialUrl:
    def test_builds_url_with_params(self):
        url = _build_initial_url("https://example.com", WORDPRESS_ENDPOINTS["posts"], {"per_page": 100})
        assert url == "https://example.com/wp-json/wp/v2/posts?per_page=100"

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


class TestIsSameHost:
    @pytest.mark.parametrize(
        "url, site_url, expected",
        [
            ("https://example.com/wp-json/wp/v2/posts?page=2", "https://example.com", True),
            # Scheme downgrade to http when configured https must be rejected (credential exposure).
            ("http://example.com/wp-json/wp/v2/posts?page=2", "https://example.com", False),
            # Foreign / internal host must be rejected (SSRF).
            ("https://169.254.169.254/latest/meta-data/", "https://example.com", False),
            # Anonymous http site: an http next URL on the same host is allowed.
            ("http://example.com/wp-json/wp/v2/posts?page=2", "http://example.com", True),
        ],
    )
    def test_is_same_host(self, url, site_url, expected):
        assert _is_same_host(url, site_url) is expected


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(wordpress_module, "make_tracked_session", return_value=session)

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_msg_substr",
        [
            (200, True, None),
            (401, False, "Invalid WordPress username or application password"),
            (403, False, "anonymous request"),
            (404, False, "REST API not found"),
        ],
    )
    def test_status_code_mapping(self, status_code, expected_valid, expected_msg_substr):
        with self._patch_session(_response(status_code=status_code)):
            valid, msg = validate_credentials("https://example.com", None, None)
            assert valid is expected_valid
            if expected_msg_substr is None:
                assert msg is None
            else:
                assert expected_msg_substr in (msg or "")

    def test_403_with_credentials_points_at_authorization_header(self):
        # With credentials, a 403 most often means the Authorization header was stripped before reaching
        # WordPress, so the message must call that out rather than blaming the credentials.
        with self._patch_session(_response(status_code=403)):
            valid, msg = validate_credentials("https://example.com", "admin", "app pass word")
            assert valid is False
            assert "Authorization header" in (msg or "")

    def test_invalid_site_url(self):
        valid, msg = validate_credentials("", None, None)
        assert valid is False
        assert msg == "Invalid WordPress site URL"

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials("https://example.com", None, None)
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        with self._patch_session(_response(status_code=302)) as patched:
            valid, msg = validate_credentials("https://example.com", None, None)
            assert valid is False
            assert msg == HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_rejects_plaintext_http_when_credentials_present(self):
        # Basic-auth credentials must never be sent over plaintext HTTP.
        with self._patch_session(_response(status_code=200)) as patched:
            valid, msg = validate_credentials("http://example.com", "admin", "app pass word")
            assert valid is False
            assert msg == HTTP_NOT_ALLOWED_ERROR
            patched.return_value.get.assert_not_called()

    def test_allows_plaintext_http_when_anonymous(self):
        # No credentials -> nothing to leak, so anonymous http is permitted.
        with self._patch_session(_response(status_code=200)):
            valid, msg = validate_credentials("http://example.com", None, None)
            assert valid is True
            assert msg is None

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(wordpress_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(_response(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("https://10.0.0.1", None, None, team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()


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
        response = wordpress_source(
            site_url="https://example.com",
            username=None,
            application_password=None,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
            team_id=1,
        )
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
    def _run(self, manager, responses, endpoint="posts", site_url="https://example.com", **kwargs):
        session = mock.MagicMock()
        session.get.side_effect = responses
        with (
            mock.patch.object(wordpress_module, "make_tracked_session", return_value=session),
            mock.patch.object(wordpress_module, "Batcher", _FakeBatcher),
        ):
            rows: list[Any] = []
            for table in get_rows(
                site_url=site_url,
                username=None,
                application_password=None,
                endpoint=endpoint,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                team_id=1,
                **kwargs,
            ):
                rows.extend(table)
        return rows, session

    def test_follows_link_header_across_pages(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _response(
            json_data=[{"id": 1}, {"id": 2}],
            link='<https://example.com/wp-json/wp/v2/posts?page=2>; rel="next"',
        )
        page2 = _response(json_data=[{"id": 3}])
        rows, session = self._run(manager, [page1, page2])

        assert [r["id"] for r in rows] == [1, 2, 3]
        second_url = session.get.call_args_list[1].args[0]
        assert second_url == "https://example.com/wp-json/wp/v2/posts?page=2"

    def test_saves_state_after_yielding(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        self._run(manager, [_response(json_data=[{"id": 1}])])

        assert manager.save_state.called
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, WordpressResumeConfig)

    def test_resumes_from_saved_state(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = WordpressResumeConfig(
            next_url="https://example.com/wp-json/wp/v2/posts?page=5"
        )
        rows, session = self._run(manager, [_response(json_data=[{"id": 9}])])

        first_url = session.get.call_args_list[0].args[0]
        assert first_url == "https://example.com/wp-json/wp/v2/posts?page=5"
        assert [r["id"] for r in rows] == [9]

    def test_empty_page_terminates(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        empty = _response(
            json_data=[],
            link='<https://example.com/wp-json/wp/v2/posts?page=2>; rel="next"',
        )
        rows, session = self._run(manager, [empty])

        assert rows == []
        assert session.get.call_count == 1

    def test_does_not_follow_next_url_on_foreign_host(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _response(
            json_data=[{"id": 1}],
            link='<http://169.254.169.254/latest/meta-data/>; rel="next"',
        )
        rows, session = self._run(manager, [page1])

        assert [r["id"] for r in rows] == [1]
        assert session.get.call_count == 1

    def test_ignores_resume_url_on_foreign_host(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = WordpressResumeConfig(next_url="http://169.254.169.254/latest/meta-data/")
        rows, session = self._run(manager, [_response(json_data=[{"id": 1}])])

        first_url = session.get.call_args_list[0].args[0]
        assert first_url.startswith("https://example.com/wp-json/wp/v2/posts")
        assert [r["id"] for r in rows] == [1]

    def test_does_not_follow_scheme_downgrade_next_url(self):
        # A Link header that downgrades https->http on the configured host must not be followed.
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _response(
            json_data=[{"id": 1}],
            link='<http://example.com/wp-json/wp/v2/posts?page=2>; rel="next"',
        )
        rows, session = self._run(manager, [page1])

        assert [r["id"] for r in rows] == [1]
        assert session.get.call_count == 1

    def test_raises_on_redirect(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        with pytest.raises(WordpressHostNotAllowedError) as exc:
            self._run(manager, [_response(status_code=302)])
        assert HOST_NOT_ALLOWED_ERROR in str(exc.value)

    def test_unsafe_host_error_is_marked_non_retryable(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        with (
            mock.patch.object(wordpress_module, "_is_host_safe", return_value=(False, "internal address")),
            pytest.raises(WordpressHostNotAllowedError) as exc,
        ):
            self._run(manager, [_response(json_data=[{"id": 1}])])
        assert HOST_NOT_ALLOWED_ERROR in str(exc.value)

    def test_rejects_plaintext_http_with_credentials_before_request(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        session = mock.MagicMock()
        with (
            mock.patch.object(wordpress_module, "make_tracked_session", return_value=session),
            mock.patch.object(wordpress_module, "Batcher", _FakeBatcher),
            pytest.raises(WordpressHostNotAllowedError) as exc,
        ):
            list(
                get_rows(
                    site_url="http://example.com",
                    username="admin",
                    application_password="app pass word",
                    endpoint="posts",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    team_id=1,
                )
            )
        assert HTTP_NOT_ALLOWED_ERROR in str(exc.value)
        session.get.assert_not_called()

    def test_passes_allow_redirects_false(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        _rows, session = self._run(manager, [_response(json_data=[{"id": 1}])])
        assert session.get.call_args.kwargs["allow_redirects"] is False


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
