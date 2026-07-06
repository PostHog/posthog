from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress import wordpress as wordpress_module
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.settings import WORDPRESS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.wordpress import (
    ANONYMOUS_FORBIDDEN_ERROR,
    AUTH_REQUIRED_ERROR,
    CREDENTIALS_IGNORED_ERROR,
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    INVALID_CREDENTIALS_ERROR,
    USER_AGENT,
    WPCOM_AUTH_REQUIRED_TABLE_ERROR,
    WPCOM_PRIVATE_SITE_ERROR,
    WPCOM_SITE_NOT_FOUND_ERROR,
    WordpressComAccessError,
    WordpressHostNotAllowedError,
    WordpressResumeConfig,
    _build_initial_params,
    _build_initial_url,
    _direct_api_base,
    _format_incremental_value,
    _get_headers,
    _is_within_api_base,
    _is_wpcom_host,
    _parse_next_url,
    _proxy_api_base,
    get_rows,
    normalize_host,
    validate_credentials,
    wordpress_source,
)

WPCOM_PROXY_BASE = "https://public-api.wordpress.com/wp/v2/sites/example.wordpress.com"


def _response(
    *,
    status_code: int = 200,
    json_data: Any = None,
    link: Optional[str] = None,
    text: str = "",
    headers: Optional[dict[str, str]] = None,
) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (301, 302, 303, 307, 308)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    response.headers = {**({"Link": link} if link else {}), **(headers or {})}
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
        # Some hosts/WAFs 403 the default python-requests User-Agent, so we must identify ourselves.
        assert headers["User-Agent"] == USER_AGENT

    def test_partial_credentials_are_anonymous(self):
        # A username without a password (or vice versa) is not enough to authenticate.
        assert "Authorization" not in _get_headers("admin", "")
        assert "Authorization" not in _get_headers("", "secret")

    def test_basic_auth_header_is_base64_of_user_colon_password(self):
        import base64

        headers = _get_headers("admin", "abcd efgh")
        expected = base64.b64encode(b"admin:abcd efgh").decode()
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["User-Agent"] == USER_AGENT


class TestIsWpcomHost:
    @pytest.mark.parametrize(
        "host, expected",
        [
            ("example.wordpress.com", True),
            ("wordpress.com", True),
            ("example.com", False),
            # Suffix matching must not swallow lookalike hosts.
            ("evil-wordpress.com", False),
            ("example.wordpress.com.evil.com", False),
        ],
    )
    def test_is_wpcom_host(self, host, expected):
        assert _is_wpcom_host(host) is expected


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
        url = _build_initial_url(
            _direct_api_base("https://example.com"), WORDPRESS_ENDPOINTS["posts"], {"per_page": 100}
        )
        assert url == "https://example.com/wp-json/wp/v2/posts?per_page=100"

    def test_builds_proxy_url(self):
        url = _build_initial_url(
            _proxy_api_base("example.wordpress.com"), WORDPRESS_ENDPOINTS["posts"], {"per_page": 100}
        )
        assert url == f"{WPCOM_PROXY_BASE}/posts?per_page=100"


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


class TestIsWithinApiBase:
    @pytest.mark.parametrize(
        "url, api_base, expected",
        [
            ("https://example.com/wp-json/wp/v2/posts?page=2", "https://example.com/wp-json/wp/v2", True),
            # Scheme downgrade to http when configured https must be rejected (credential exposure).
            ("http://example.com/wp-json/wp/v2/posts?page=2", "https://example.com/wp-json/wp/v2", False),
            # Foreign / internal host must be rejected (SSRF).
            ("https://169.254.169.254/latest/meta-data/", "https://example.com/wp-json/wp/v2", False),
            # Anonymous http site: an http next URL on the same host is allowed.
            ("http://example.com/wp-json/wp/v2/posts?page=2", "http://example.com/wp-json/wp/v2", True),
            # Same host but outside the API base path.
            ("https://example.com/xmlrpc.php", "https://example.com/wp-json/wp/v2", False),
            # Proxied pagination stays inside the proxied site's base.
            (f"{WPCOM_PROXY_BASE}/posts?page=2", WPCOM_PROXY_BASE, True),
            # A stale direct-style resume URL is outside the proxy base.
            ("https://example.wordpress.com/wp-json/wp/v2/posts?page=2", WPCOM_PROXY_BASE, False),
            # Another site's path on the shared proxy host must be rejected.
            ("https://public-api.wordpress.com/wp/v2/sites/other.wordpress.com/posts", WPCOM_PROXY_BASE, False),
            (f"{WPCOM_PROXY_BASE}-evil/posts", WPCOM_PROXY_BASE, False),
        ],
    )
    def test_is_within_api_base(self, url, api_base, expected):
        assert _is_within_api_base(url, api_base) is expected


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None, responses=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        elif responses is not None:
            session.get.side_effect = responses
        else:
            session.get.return_value = response
        return mock.patch.object(wordpress_module, "make_tracked_session", return_value=session)

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_msg",
        [
            (200, True, None),
            (401, False, AUTH_REQUIRED_ERROR),
            (403, False, ANONYMOUS_FORBIDDEN_ERROR),
            (404, False, "REST API not found"),
        ],
    )
    def test_anonymous_status_code_mapping(self, status_code, expected_valid, expected_msg):
        with self._patch_session(_response(status_code=status_code)) as patched:
            valid, msg = validate_credentials("https://example.com", None, None)
            assert valid is expected_valid
            if expected_msg is None:
                assert msg is None
            else:
                assert expected_msg in (msg or "")
            probe_url = patched.return_value.get.call_args.args[0]
            assert probe_url == "https://example.com/wp-json/wp/v2/posts?per_page=1"

    def test_anonymous_403_does_not_blame_credentials(self):
        # The customer-facing regression: with no credentials supplied, a 403 must not claim
        # "these credentials lack permission".
        with self._patch_session(_response(status_code=403)):
            _valid, msg = validate_credentials("https://example.com", None, None)
            assert "credentials lack" not in (msg or "")

    def test_credentialed_probe_uses_users_me(self):
        # /users/me exercises auth for real; a public-collection probe silently validates garbage
        # credentials on sites where application passwords are unavailable.
        with self._patch_session(_response(status_code=200)) as patched:
            valid, msg = validate_credentials("https://example.com", "admin", "app pass word")
            assert (valid, msg) == (True, None)
            probe_url = patched.return_value.get.call_args.args[0]
            assert probe_url == "https://example.com/wp-json/wp/v2/users/me"

    @pytest.mark.parametrize(
        "json_data, expected_msg",
        [
            ({"code": "rest_not_logged_in", "message": "You are not currently logged in."}, CREDENTIALS_IGNORED_ERROR),
            ({"code": "incorrect_password", "message": "..."}, INVALID_CREDENTIALS_ERROR),
            ({"code": "invalid_username", "message": "..."}, INVALID_CREDENTIALS_ERROR),
            (None, INVALID_CREDENTIALS_ERROR),
        ],
    )
    def test_credentialed_401_mapping(self, json_data, expected_msg):
        with self._patch_session(_response(status_code=401, json_data=json_data)):
            valid, msg = validate_credentials("https://example.com", "admin", "app pass word")
            assert valid is False
            assert msg == expected_msg

    def test_credentialed_403_blames_credentials(self):
        with self._patch_session(_response(status_code=403)):
            valid, msg = validate_credentials("https://example.com", "admin", "app pass word")
            assert valid is False
            assert "credentials lack permission" in (msg or "")

    def test_users_route_blocked_falls_back_to_posts_probe(self):
        # Security plugins often hide the users routes (rest_no_route) while the REST API itself works.
        blocked = _response(status_code=404, json_data={"code": "rest_no_route", "message": "No route"})
        with self._patch_session(responses=[blocked, _response(status_code=200)]) as patched:
            valid, msg = validate_credentials("https://example.com", "admin", "app pass word")
            assert (valid, msg) == (True, None)
            urls = [call.args[0] for call in patched.return_value.get.call_args_list]
            assert urls == [
                "https://example.com/wp-json/wp/v2/users/me",
                "https://example.com/wp-json/wp/v2/posts?per_page=1",
            ]

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

    def test_rejects_redirect_response_without_location(self):
        with self._patch_session(_response(status_code=302)) as patched:
            valid, msg = validate_credentials("https://example.com", None, None)
            assert valid is False
            assert msg == HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_redirect_surfaces_target_url(self):
        # www canonicalization and Business-plan subdomain redirects are legit; tell the user which
        # URL to enter instead of a bare "not allowed".
        redirect = _response(status_code=301, headers={"Location": "https://www.example.com/wp-json/wp/v2/posts?a=1"})
        with self._patch_session(redirect):
            valid, msg = validate_credentials("https://example.com", None, None)
            assert valid is False
            assert "https://www.example.com" in (msg or "")
            assert "a=1" not in (msg or "")  # query stripped: Location is server-controlled

    def test_redirect_to_wpcom_typo_page_means_no_such_site(self):
        redirect = _response(status_code=302, headers={"Location": "https://wordpress.com/typo/?subdomain=examplee"})
        with self._patch_session(redirect):
            valid, msg = validate_credentials("https://examplee.wordpress.com", None, None)
            assert valid is False
            assert msg == WPCOM_SITE_NOT_FOUND_ERROR

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

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_msg",
        [
            (200, True, None),
            (401, False, WPCOM_PRIVATE_SITE_ERROR),
            (403, False, WPCOM_PRIVATE_SITE_ERROR),
            (404, False, WPCOM_SITE_NOT_FOUND_ERROR),
        ],
    )
    def test_wpcom_host_probes_via_proxy(self, status_code, expected_valid, expected_msg):
        with (
            mock.patch.object(wordpress_module, "_is_host_safe") as host_safe,
            self._patch_session(_response(status_code=status_code, json_data=[])) as patched,
        ):
            valid, msg = validate_credentials("https://example.wordpress.com", None, None, team_id=99)
            assert valid is expected_valid
            assert msg == expected_msg
            probe_url = patched.return_value.get.call_args.args[0]
            assert probe_url == f"{WPCOM_PROXY_BASE}/posts?per_page=1"
            # Proxied traffic only ever reaches the fixed public proxy host, so the per-host SSRF
            # check is skipped.
            host_safe.assert_not_called()

    def test_wpcom_host_never_sends_credentials(self):
        # wp.com "application passwords" are OAuth credentials for wordpress.com itself; forwarding
        # them as Basic auth would leak them without ever working.
        with self._patch_session(_response(status_code=200, json_data=[])) as patched:
            valid, _msg = validate_credentials("https://example.wordpress.com", "admin", "app pass word")
            assert valid is True
            sent_headers = patched.return_value.get.call_args.kwargs["headers"]
            assert "Authorization" not in sent_headers

    def test_wpcom_served_custom_domain_falls_back_to_proxy(self):
        # Personal/Premium wp.com sites on custom domains 404 the direct REST path but stamp the
        # wp.com host header; their content is only served by the proxy.
        direct_404 = _response(status_code=404, headers={"host-header": "WordPress.com"})
        with self._patch_session(responses=[direct_404, _response(status_code=200, json_data=[])]) as patched:
            valid, msg = validate_credentials("https://example.com", None, None)
            assert (valid, msg) == (True, None)
            urls = [call.args[0] for call in patched.return_value.get.call_args_list]
            assert urls == [
                "https://example.com/wp-json/wp/v2/posts?per_page=1",
                "https://public-api.wordpress.com/wp/v2/sites/example.com/posts?per_page=1",
            ]


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
    def _run(
        self,
        manager,
        responses,
        endpoint="posts",
        site_url="https://example.com",
        username=None,
        application_password=None,
        **kwargs,
    ):
        session = mock.MagicMock()
        session.get.side_effect = responses
        with (
            mock.patch.object(wordpress_module, "make_tracked_session", return_value=session),
            mock.patch.object(wordpress_module, "Batcher", _FakeBatcher),
        ):
            rows: list[Any] = []
            for table in get_rows(
                site_url=site_url,
                username=username,
                application_password=application_password,
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

    def test_wpcom_site_paginates_via_proxy(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _response(json_data=[{"id": 1}], link=f'<{WPCOM_PROXY_BASE}/posts?page=2>; rel="next"')
        page2 = _response(json_data=[{"id": 2}])
        rows, session = self._run(manager, [page1, page2], site_url="https://example.wordpress.com")

        assert [r["id"] for r in rows] == [1, 2]
        urls = [call.args[0] for call in session.get.call_args_list]
        assert urls[0].startswith(f"{WPCOM_PROXY_BASE}/posts?")
        assert urls[1] == f"{WPCOM_PROXY_BASE}/posts?page=2"

    def test_wpcom_site_never_sends_credentials(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        _rows, session = self._run(
            manager,
            [_response(json_data=[{"id": 1}])],
            site_url="https://example.wordpress.com",
            username="admin",
            application_password="app pass word",
        )
        assert "Authorization" not in session.get.call_args.kwargs["headers"]

    def test_wpcom_served_direct_failure_falls_back_to_proxy(self):
        # Personal/Premium wp.com sites on custom domains 404 the direct REST path but stamp the
        # wp.com host header; the run must restart on the proxy, without forwarding credentials.
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        direct_404 = _response(status_code=404, headers={"host-header": "WordPress.com"})
        rows, session = self._run(
            manager,
            [direct_404, _response(json_data=[{"id": 7}])],
            username="admin",
            application_password="app pass word",
        )

        assert [r["id"] for r in rows] == [7]
        first_call, second_call = session.get.call_args_list
        assert first_call.args[0].startswith("https://example.com/wp-json/wp/v2/posts?")
        assert "Authorization" in first_call.kwargs["headers"]
        assert second_call.args[0].startswith("https://public-api.wordpress.com/wp/v2/sites/example.com/posts?")
        assert "Authorization" not in second_call.kwargs["headers"]

    def test_wpcom_served_failure_mid_pagination_raises(self):
        # Flipping to the proxy after pages were already yielded would mix bases mid-run.
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _response(
            json_data=[{"id": 1}],
            link='<https://example.com/wp-json/wp/v2/posts?page=2>; rel="next"',
        )
        direct_404 = _response(status_code=404, headers={"host-header": "WordPress.com"})
        with pytest.raises(WordpressComAccessError) as exc:
            self._run(manager, [page1, direct_404])
        assert WPCOM_PRIVATE_SITE_ERROR in str(exc.value)

    @pytest.mark.parametrize(
        "endpoint, expected_msg",
        [
            ("media", WPCOM_AUTH_REQUIRED_TABLE_ERROR),
            ("users", WPCOM_AUTH_REQUIRED_TABLE_ERROR),
            ("posts", WPCOM_PRIVATE_SITE_ERROR),
        ],
    )
    def test_proxied_auth_failure_maps_to_wpcom_error(self, endpoint, expected_msg):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        with pytest.raises(WordpressComAccessError) as exc:
            self._run(
                manager,
                [_response(status_code=401, json_data={"code": "unauthorized"})],
                endpoint=endpoint,
                site_url="https://example.wordpress.com",
            )
        assert expected_msg in str(exc.value)

    def test_stale_direct_resume_url_restarts_at_proxy_initial(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = WordpressResumeConfig(
            next_url="https://example.wordpress.com/wp-json/wp/v2/posts?page=5"
        )
        rows, session = self._run(manager, [_response(json_data=[{"id": 3}])], site_url="https://example.wordpress.com")

        assert [r["id"] for r in rows] == [3]
        first_url = session.get.call_args_list[0].args[0]
        assert first_url.startswith(f"{WPCOM_PROXY_BASE}/posts?")


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
