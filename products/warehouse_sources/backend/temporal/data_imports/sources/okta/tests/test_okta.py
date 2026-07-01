from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.okta import okta as okta_module
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.okta import (
    OktaResumeConfig,
    _build_initial_params,
    _build_initial_url,
    _format_incremental_value,
    _parse_next_url,
    get_rows,
    normalize_domain,
    okta_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.settings import OKTA_ENDPOINTS


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
    """Yields whatever has been buffered on every ``should_yield`` check, so the per-item
    save_state path in ``get_rows`` is exercised without needing 2000+ rows."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._buf: list[Any] = []

    def batch(self, item: Any) -> None:
        self._buf.append(item)

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return len(self._buf) > 0

    def get_table(self) -> list[Any]:
        rows, self._buf = self._buf, []
        return rows


class TestNormalizeDomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("example.okta.com", "example.okta.com"),
            ("https://example.okta.com", "example.okta.com"),
            ("http://example.okta.com/", "example.okta.com"),
            ("  example.okta.com  ", "example.okta.com"),
            ("example.okta.com/api/v1", "example.okta.com"),
            ("https://example.okta.com/api/v1/users", "example.okta.com"),
        ],
    )
    def test_normalize_domain(self, raw, expected):
        assert normalize_domain(raw) == expected


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected

    def test_no_offset_suffix(self):
        assert "+00:00" not in _format_incremental_value(datetime(2026, 3, 4, tzinfo=UTC))


class TestBuildInitialParams:
    def test_filter_endpoint_incremental(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["users"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="lastUpdated",
        )
        assert params["filter"] == 'lastUpdated gt "2024-01-01T00:00:00.000Z"'
        assert params["limit"] == 200

    def test_applications_never_sends_filter(self):
        # Okta's Apps API `filter` does not support lastUpdated, so an incremental run must
        # not send a server-side filter — it would 400.
        params = _build_initial_params(
            OKTA_ENDPOINTS["applications"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="lastUpdated",
        )
        assert params == {"limit": 200}

    def test_filter_endpoint_no_watermark_has_no_filter(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["users"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="lastUpdated",
        )
        assert "filter" not in params

    def test_filter_endpoint_full_refresh_has_no_filter(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["groups"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field=None,
        )
        assert "filter" not in params

    def test_logs_incremental_uses_since(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["logs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="published",
        )
        assert params["since"] == "2024-01-01T00:00:00.000Z"
        assert params["sortOrder"] == "ASCENDING"

    def test_logs_first_sync_applies_lookback(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["logs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="published",
        )
        # The 90-day lookback means `since` is populated even without a stored watermark.
        assert "since" in params
        assert params["sortOrder"] == "ASCENDING"

    def test_logs_full_refresh_has_no_since(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["logs"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert "since" not in params
        assert params["sortOrder"] == "ASCENDING"

    def test_logs_full_refresh_ignores_stray_watermark(self):
        # Even if a watermark leaks in, a non-incremental run must not apply a `since` filter.
        params = _build_initial_params(
            OKTA_ENDPOINTS["logs"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field=None,
        )
        assert "since" not in params

    def test_non_incremental_endpoint_only_limit(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["group_rules"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field=None,
        )
        assert params == {"limit": 200}


class TestBuildInitialUrl:
    def test_builds_url_with_params(self):
        url = _build_initial_url("example.okta.com", OKTA_ENDPOINTS["users"], {"limit": 200})
        assert url == "https://example.okta.com/api/v1/users?limit=200"

    def test_builds_url_without_params(self):
        url = _build_initial_url("example.okta.com", OKTA_ENDPOINTS["user_types"], {})
        assert url == "https://example.okta.com/api/v1/meta/types/user"


class TestParseNextUrl:
    @pytest.mark.parametrize(
        "header, expected",
        [
            ("", None),
            ('<https://x/api/v1/users>; rel="self"', None),
            ('<https://x/api/v1/users?after=abc>; rel="next"', "https://x/api/v1/users?after=abc"),
            (
                '<https://x/api/v1/users>; rel="self", <https://x/api/v1/users?after=abc>; rel="next"',
                "https://x/api/v1/users?after=abc",
            ),
        ],
    )
    def test_parse(self, header, expected):
        assert _parse_next_url(header) == expected


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(okta_module, "make_tracked_session", return_value=session)

    def test_success(self):
        with self._patch_session(_response(status_code=200)):
            assert validate_credentials("example.okta.com", "tok") == (True, None)

    def test_invalid_token(self):
        with self._patch_session(_response(status_code=401)):
            valid, msg = validate_credentials("example.okta.com", "tok")
            assert valid is False
            assert "Invalid Okta API token" == msg

    def test_403_at_source_create_is_accepted(self):
        with self._patch_session(_response(status_code=403)):
            assert validate_credentials("example.okta.com", "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with self._patch_session(_response(status_code=403)):
            valid, msg = validate_credentials("example.okta.com", "tok", schema_name="users")
            assert valid is False
            assert msg is not None

    @pytest.mark.parametrize("bad_domain", ["", "not a domain!", "https://"])
    def test_invalid_domain_short_circuits(self, bad_domain):
        valid, msg = validate_credentials(bad_domain, "tok")
        assert valid is False
        assert msg == "Invalid Okta domain"

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials("example.okta.com", "tok")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        # A validated host that 3xx-redirects (potentially to an internal address) must be rejected,
        # not followed (SSRF).
        with self._patch_session(_response(status_code=302)) as patched:
            valid, msg = validate_credentials("example.okta.com", "tok")
            assert valid is False
            assert msg == okta_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        # When a team_id is supplied, a host that resolves to an internal address is rejected
        # before any HTTP request is made (SSRF guard).
        with (
            mock.patch.object(okta_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(_response(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()


class TestOktaSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_key, partition_key",
        [
            ("users", "id", "created"),
            ("groups", "id", "created"),
            ("applications", "id", "created"),
            ("logs", "uuid", "published"),
            ("group_rules", "id", "created"),
            ("user_types", "id", None),
        ],
    )
    def test_response_shape(self, endpoint, primary_key, partition_key):
        response = okta_source(
            domain="example.okta.com",
            api_key="tok",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
            team_id=1,
        )
        assert response.name == endpoint
        assert response.primary_keys == [primary_key]
        assert response.sort_mode == "asc"
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestGetRows:
    def _run(self, manager, responses):
        session = mock.MagicMock()
        session.get.side_effect = responses
        with (
            mock.patch.object(okta_module, "make_tracked_session", return_value=session),
            mock.patch.object(okta_module, "Batcher", _FakeBatcher),
        ):
            rows: list[Any] = []
            for table in get_rows(
                domain="example.okta.com",
                api_key="tok",
                endpoint="users",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                team_id=1,
            ):
                rows.extend(table)
        return rows, session

    def test_follows_link_header_across_pages(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _response(
            json_data=[{"id": "1"}, {"id": "2"}],
            link='<https://example.okta.com/api/v1/users?after=cur>; rel="next"',
        )
        page2 = _response(json_data=[{"id": "3"}])
        rows, session = self._run(manager, [page1, page2])

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        # Second fetch follows the Link header URL.
        second_url = session.get.call_args_list[1].args[0]
        assert second_url == "https://example.okta.com/api/v1/users?after=cur"

    def test_saves_state_after_yielding(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page = _response(json_data=[{"id": "1"}])
        self._run(manager, [page])

        assert manager.save_state.called
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, OktaResumeConfig)

    def test_resumes_from_saved_state(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = OktaResumeConfig(
            next_url="https://example.okta.com/api/v1/users?after=resume"
        )
        rows, session = self._run(manager, [_response(json_data=[{"id": "9"}])])

        first_url = session.get.call_args_list[0].args[0]
        assert first_url == "https://example.okta.com/api/v1/users?after=resume"
        assert [r["id"] for r in rows] == ["9"]

    def test_empty_page_terminates_even_with_next_link(self):
        # The System Log always returns a next link, so an empty page must end pagination.
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        empty = _response(
            json_data=[],
            link='<https://example.okta.com/api/v1/logs?after=x>; rel="next"',
        )
        rows, session = self._run(manager, [empty])

        assert rows == []
        assert session.get.call_count == 1

    def test_does_not_follow_next_url_on_foreign_host(self):
        # A server-controlled Link header pointing off-org must not be followed (SSRF guard).
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _response(
            json_data=[{"id": "1"}],
            link='<http://169.254.169.254/latest/meta-data/>; rel="next"',
        )
        rows, session = self._run(manager, [page1])

        assert [r["id"] for r in rows] == ["1"]
        assert session.get.call_count == 1

    def test_ignores_resume_url_on_foreign_host(self):
        # A poisoned resume URL must fall back to the initial org URL, not be followed.
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = OktaResumeConfig(next_url="http://169.254.169.254/latest/meta-data/")
        rows, session = self._run(manager, [_response(json_data=[{"id": "1"}])])

        first_url = session.get.call_args_list[0].args[0]
        assert first_url.startswith("https://example.okta.com/api/v1/users")
        assert [r["id"] for r in rows] == ["1"]

    def test_does_not_follow_redirects(self):
        # Requests are made with allow_redirects=False, and a redirect response is rejected rather
        # than followed to a (potentially internal) Location (SSRF).
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        with pytest.raises(okta_module.OktaHostNotAllowedError):
            self._run(manager, [_response(status_code=302)])

    def test_passes_allow_redirects_false(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        _rows, session = self._run(manager, [_response(json_data=[{"id": "1"}])])
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.okta.okta import _parse_retry_after

        response = mock.MagicMock()
        response.headers = header
        assert _parse_retry_after(response) == expected

    def test_retry_wait_prefers_retry_after(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.okta.okta import (
            OktaRetryableError,
            _retry_wait,
        )

        state = mock.MagicMock()
        state.outcome.exception.return_value = OktaRetryableError("rate limited", retry_after=7.0)
        assert _retry_wait(state) == 7.0
