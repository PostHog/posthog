import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm import nocrm
from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.nocrm import (
    PAGE_SIZE,
    NoCRMConfigError,
    NoCRMResumeConfig,
    _base_url,
    _build_base_params,
    _clamp_future_value_to_now,
    _format_updated_after,
    nocrm_source,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.settings import NOCRM_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the nocrm module.
NOCRM_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.nocrm.make_tracked_session"
)
# The framework retries retryable statuses via tenacity; patch its sleep so tests don't block.
TENACITY_SLEEP_PATCH = "tenacity.nap.time.sleep"


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare_label", "acme", "acme"),
            ("uppercase", "ACME", "acme"),
            ("whitespace", "  acme  ", "acme"),
            ("full_host", "acme.nocrm.io", "acme"),
            ("full_url", "https://acme.nocrm.io/", "acme"),
            ("url_with_path", "https://acme.nocrm.io/api/v2/leads", "acme"),
            ("hyphenated", "acme-sales", "acme-sales"),
            # A stray path segment is truncated to the leading label rather than reaching the host.
            ("path_truncated", "acme/evil", "acme"),
        ]
    )
    def test_valid_subdomains_reduce_to_label(self, _name: str, value: str, expected: str) -> None:
        assert normalize_subdomain(value) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("dot_breakout", "acme.evil"),
            ("at_breakout", "evil@acme"),
            ("leading_hyphen", "-acme"),
            ("underscore", "acme_sales"),
            ("space_inside", "acme corp"),
        ]
    )
    def test_invalid_subdomains_raise(self, _name: str, value: str) -> None:
        with pytest.raises(NoCRMConfigError):
            normalize_subdomain(value)

    def test_base_url_is_pinned_to_nocrm_origin(self) -> None:
        # Only the subdomain label is user-controlled; the origin is always *.nocrm.io.
        assert _base_url("acme") == "https://acme.nocrm.io/api/v2"
        assert _base_url("https://acme.nocrm.io") == "https://acme.nocrm.io/api/v2"


class TestFormatUpdatedAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_updated_after(value) == expected

    def test_non_utc_datetime_is_converted_to_utc(self) -> None:
        from datetime import timedelta, timezone

        value = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone(timedelta(hours=5)))
        assert _format_updated_after(value) == "2026-03-04T07:00:00Z"


class TestClampFutureValueToNow:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, 21, 46, 42, tzinfo=UTC)) == datetime(
            2026, 6, 15, 12, 0, 0, tzinfo=UTC
        )

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_datetime_is_unchanged(self) -> None:
        value = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        assert _clamp_future_value_to_now(value) == value

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("cursor") == "cursor"


class TestBuildBaseParams:
    def test_leads_full_refresh_sorts_by_id_without_filter(self) -> None:
        params = _build_base_params(
            NOCRM_ENDPOINTS["leads"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert params == {"order": "id", "direction": "asc"}

    def test_leads_incremental_adds_updated_after_and_sorts_by_last_update(self) -> None:
        params = _build_base_params(
            NOCRM_ENDPOINTS["leads"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params["updated_after"] == "2026-03-04T02:58:14Z"
        # Incremental syncs must sort ascending by the changed field so the asc watermark advances.
        assert params["order"] == "last_update"
        assert params["direction"] == "asc"

    def test_leads_incremental_without_watermark_omits_filter(self) -> None:
        params = _build_base_params(
            NOCRM_ENDPOINTS["leads"], should_use_incremental_field=True, db_incremental_field_last_value=None
        )
        assert "updated_after" not in params

    @parameterized.expand([("users",), ("teams",), ("steps",), ("pipelines",), ("categories",), ("tags",), ("fields",)])
    def test_metadata_endpoints_send_no_order_or_filter(self, endpoint: str) -> None:
        # These endpoints don't document an `order` param, so we must not send one (nor a filter).
        params = _build_base_params(
            NOCRM_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {}


def _page(n: int, start_id: int = 1) -> list[dict]:
    return [{"id": start_id + i} for i in range(n)]


def _response(
    items: list[dict] | None = None,
    *,
    total: int | None = None,
    status: int = 200,
    reason: str = "OK",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = "https://acme.nocrm.io/api/v2/leads"
    resp._content = body if body is not None else json.dumps(items or []).encode()
    if total is not None:
        resp.headers["X-TOTAL-COUNT"] = str(total)
    if headers:
        resp.headers.update(headers)
    return resp


def _make_manager(resume_state: NoCRMResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[requests.Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so a copy must be taken as each
    request is prepared rather than read afterwards.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = "https://acme.nocrm.io/api/v2/leads"
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(
    manager: mock.MagicMock,
    *,
    endpoint: str = "leads",
    **kwargs: Any,
) -> Any:
    return nocrm_source(
        api_key="key",
        subdomain="acme",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response: Any) -> list[dict]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_page(PAGE_SIZE, 1)), _response(_page(3, PAGE_SIZE + 1))])

        rows = _rows(_source(_make_manager()))

        assert len(rows) == PAGE_SIZE + 3
        # Two requests, second offset advanced by the full first page.
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_leads_full_refresh_sends_sort_params(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_page(2, 1))])

        _rows(_source(_make_manager()))
        assert params[0]["order"] == "id"
        assert params[0]["direction"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_leads_incremental_sends_updated_after(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_page(2, 1))])

        _rows(
            _source(
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )
        assert params[0]["updated_after"] == "2026-03-04T02:58:14Z"
        assert params[0]["order"] == "last_update"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_total_count_reached(self, MockSession: mock.MagicMock) -> None:
        # A full page whose X-TOTAL-COUNT equals the page size must not trigger a second request.
        session = MockSession.return_value
        _wire(session, [_response(_page(PAGE_SIZE), total=PAGE_SIZE)])

        rows = _rows(_source(_make_manager()))
        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_offset_is_ignored(self, MockSession: mock.MagicMock) -> None:
        # An endpoint that ignores offset re-serves the same first page; the no-progress guard must
        # break the loop after the repeat instead of looping forever (merge dedupes the repeat).
        session = MockSession.return_value
        _wire(session, [_response(_page(PAGE_SIZE, 1)), _response(_page(PAGE_SIZE, 1))])

        rows = _rows(_source(_make_manager()))
        # Exactly two requests were made and iteration terminated — no infinite loop.
        assert session.send.call_count == 2
        # The repeated ids are all id 1..PAGE_SIZE (dedup drops the duplicates downstream).
        assert {r["id"] for r in rows} == set(range(1, PAGE_SIZE + 1))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        rows = _rows(_source(_make_manager()))
        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_offset_after_each_page_with_more(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_page(PAGE_SIZE, 1)), _response(_page(2, PAGE_SIZE + 1))])

        manager = _make_manager()
        _rows(_source(manager))
        # State saved once (after the full first page); not after the short final page.
        assert [call.args[0].offset for call in manager.save_state.call_args_list] == [PAGE_SIZE]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_page(2, PAGE_SIZE + 1))])

        rows = _rows(_source(_make_manager(NoCRMResumeConfig(offset=PAGE_SIZE))))
        assert len(rows) == 2
        # The first (and only) request must start at the saved offset, not 0.
        assert params[0]["offset"] == PAGE_SIZE


class TestRetryAndErrors:
    @parameterized.expand([(429,), (500,), (503,)])
    @mock.patch(TENACITY_SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(
        self, status: int, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status=status, reason="Too Many Requests"), _response(_page(2, 1))])

        rows = _rows(_source(_make_manager()))
        assert len(rows) == 2
        # The retryable status was re-issued rather than surfaced as an error.
        assert session.send.call_count == 2

    @parameterized.expand([(401, "Unauthorized"), (403, "Forbidden"), (404, "Not Found")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_http_error(self, status: int, reason: str, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status=status, reason=reason)])

        # The status text stays intact so get_non_retryable_errors can match "40x Client Error".
        with pytest.raises(HTTPError, match=f"{status} Client Error"):
            _rows(_source(_make_manager()))


class TestSSRFAndRedaction:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_is_registered_for_redaction(self, MockSession: mock.MagicMock) -> None:
        _wire(MockSession.return_value, [_response([])])
        nocrm_source(
            api_key="secret-key",
            subdomain="acme",
            endpoint="leads",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        # The framework masks the auth secret in logs and raised errors.
        assert MockSession.call_args.kwargs["redact_values"] == ("secret-key",)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_redirect_is_refused(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status=302, headers={"Location": "https://evil.example/api"})])

        # allow_redirects=False: a 3xx must be rejected so the key can't be steered off-host.
        with pytest.raises(ValueError, match="refusing to follow"):
            _rows(_source(_make_manager()))

    def test_validate_credentials_rejects_invalid_subdomain_without_request(self) -> None:
        with mock.patch.object(nocrm, "make_tracked_session") as make_session:
            assert validate_credentials("key", "acme.evil") is False
        # An invalid subdomain must fail before any authenticated request is built.
        make_session.assert_not_called()

    @mock.patch(NOCRM_SESSION_PATCH)
    def test_validate_credentials_ok_on_200(self, make_session: mock.MagicMock) -> None:
        make_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("secret-key", "acme") is True
        assert make_session.call_args.kwargs["redact_values"] == ("secret-key",)

    @mock.patch(NOCRM_SESSION_PATCH)
    def test_validate_credentials_false_on_non_200(self, make_session: mock.MagicMock) -> None:
        make_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("key", "acme") is False

    @mock.patch(NOCRM_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, make_session: mock.MagicMock) -> None:
        make_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "acme") is False


class TestSourceResponse:
    def test_leads_partitions_on_created_at(self) -> None:
        with mock.patch(CLIENT_SESSION_PATCH):
            response = _source(_make_manager())
        assert response.name == "leads"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.sort_mode == "asc"

    @parameterized.expand(
        [
            ("users",),
            ("teams",),
            ("steps",),
            ("pipelines",),
            ("categories",),
            ("tags",),
            ("fields",),
            ("activities",),
            ("client_folders",),
        ]
    )
    def test_metadata_endpoints_are_unpartitioned(self, endpoint: str) -> None:
        with mock.patch(CLIENT_SESSION_PATCH):
            response = _source(_make_manager(), endpoint=endpoint)
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
