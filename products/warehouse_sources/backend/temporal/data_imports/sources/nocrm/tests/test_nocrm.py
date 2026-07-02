from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm import nocrm
from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.nocrm import (
    PAGE_SIZE,
    NoCRMConfigError,
    NoCRMResumeConfig,
    _base_url,
    _build_base_params,
    _clamp_future_value_to_now,
    _format_updated_after,
    get_rows,
    nocrm_source,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.settings import NOCRM_ENDPOINTS


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


class _FakeResumableManager:
    def __init__(self, state: NoCRMResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[NoCRMResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> NoCRMResumeConfig | None:
        return self._state

    def save_state(self, data: NoCRMResumeConfig) -> None:
        self.saved.append(data)


def _page(n: int, start_id: int = 1) -> list[dict]:
    return [{"id": start_id + i} for i in range(n)]


def _collect(
    manager: _FakeResumableManager,
    monkeypatch: Any,
    responses: Sequence[tuple[list[dict], int | None]],
    endpoint: str = "leads",
    **kwargs: Any,
) -> tuple[list[dict], list[str]]:
    fetched: list[str] = []
    it = iter(responses)

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> tuple[list[dict], int | None]:
        fetched.append(url)
        return next(it)

    monkeypatch.setattr(nocrm, "_fetch_page", fake_fetch)
    rows: list[dict] = []
    for batch in get_rows(
        api_key="key",
        subdomain="acme",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows, fetched


class TestGetRows:
    def test_paginates_until_short_page(self, monkeypatch: Any) -> None:
        responses = [(_page(PAGE_SIZE, start_id=1), None), (_page(3, start_id=PAGE_SIZE + 1), None)]
        rows, fetched = _collect(_FakeResumableManager(), monkeypatch, responses)
        assert len(rows) == PAGE_SIZE + 3
        # Two requests, second offset advanced by the full first page.
        assert "offset=0" in fetched[0]
        assert f"offset={PAGE_SIZE}" in fetched[1]

    def test_stops_when_total_count_reached(self, monkeypatch: Any) -> None:
        # A full page whose X-TOTAL-COUNT equals the page size must not trigger a second request.
        responses = [(_page(PAGE_SIZE), PAGE_SIZE)]
        rows, fetched = _collect(_FakeResumableManager(), monkeypatch, responses)
        assert len(rows) == PAGE_SIZE
        assert len(fetched) == 1

    def test_stops_when_offset_is_ignored(self, monkeypatch: Any) -> None:
        # An endpoint that ignores offset re-serves the same first page; the no-progress guard must
        # break the loop instead of looping forever.
        same_page = _page(PAGE_SIZE, start_id=1)
        responses = [(same_page, None), (same_page, None)]
        rows, fetched = _collect(_FakeResumableManager(), monkeypatch, responses)
        assert len(rows) == PAGE_SIZE  # only the first page was yielded
        assert len(fetched) == 2

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        rows, fetched = _collect(_FakeResumableManager(), monkeypatch, [([], None)])
        assert rows == []
        assert len(fetched) == 1

    def test_saves_offset_after_each_page_with_more(self, monkeypatch: Any) -> None:
        responses = [(_page(PAGE_SIZE, start_id=1), None), (_page(2, start_id=PAGE_SIZE + 1), None)]
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, responses)
        # State saved once (after the full first page); not after the short final page.
        assert [s.offset for s in manager.saved] == [PAGE_SIZE]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(NoCRMResumeConfig(offset=PAGE_SIZE))
        responses = [(_page(2, start_id=PAGE_SIZE + 1), None)]
        rows, fetched = _collect(manager, monkeypatch, responses)
        assert len(rows) == 2
        # The first (and only) request must start at the saved offset, not 0.
        assert f"offset={PAGE_SIZE}" in fetched[0]

    def test_wrapped_object_body_is_unwrapped(self, monkeypatch: Any) -> None:
        # Defensive path: if noCRM ever wraps the array in {"data": [...]}, we still read it.
        rows, _ = _collect(_FakeResumableManager(), monkeypatch, [([{"id": 7}], None)])
        assert rows == [{"id": 7}]


class TestTokenRedaction:
    def test_get_rows_redacts_key_and_disables_redirects(self, monkeypatch: Any) -> None:
        session = MagicMock()
        make_session = MagicMock(return_value=session)
        monkeypatch.setattr(nocrm, "make_tracked_session", make_session)
        monkeypatch.setattr(nocrm, "_fetch_page", lambda *a, **k: ([], None))
        list(
            get_rows(
                api_key="secret-key",
                subdomain="acme",
                endpoint="leads",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
        )
        assert make_session.call_args.kwargs["redact_values"] == ("secret-key",)
        assert make_session.call_args.kwargs["allow_redirects"] is False

    def test_validate_credentials_rejects_invalid_subdomain_without_request(self) -> None:
        with patch.object(nocrm, "make_tracked_session") as make_session:
            assert validate_credentials("key", "acme.evil") is False
        # An invalid subdomain must fail before any authenticated request is built.
        make_session.assert_not_called()

    def test_validate_credentials_redacts_key(self) -> None:
        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        session.get.return_value = response
        with patch.object(nocrm, "make_tracked_session", return_value=session) as make_session:
            assert validate_credentials("secret-key", "acme") is True
        assert make_session.call_args.kwargs["redact_values"] == ("secret-key",)


def _response_with(status_code: int, body: bytes = b"[]", headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = body
    response.url = "https://acme.nocrm.io/api/v2/leads"
    if headers:
        response.headers.update(headers)
    return response


_fetch_page_unwrapped = nocrm._fetch_page.__wrapped__  # type: ignore[attr-defined]


class TestFetchPage:
    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with(status)
        with pytest.raises(nocrm.NoCRMRetryableError):
            _fetch_page_unwrapped(session, "https://acme.nocrm.io/api/v2/leads", {}, MagicMock())

    @parameterized.expand([(401,), (403,), (404,)])
    def test_client_errors_raise_for_status(self, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "https://acme.nocrm.io/api/v2/leads", {}, MagicMock())

    def test_parses_bare_array_and_total_count_header(self) -> None:
        session = MagicMock()
        session.get.return_value = _response_with(200, body=b'[{"id":1},{"id":2}]', headers={"X-TOTAL-COUNT": "42"})
        items, total = _fetch_page_unwrapped(session, "https://acme.nocrm.io/api/v2/leads", {}, MagicMock())
        assert items == [{"id": 1}, {"id": 2}]
        assert total == 42

    def test_missing_total_count_header_returns_none(self) -> None:
        session = MagicMock()
        session.get.return_value = _response_with(200, body=b'[{"id":1}]')
        _items, total = _fetch_page_unwrapped(session, "https://acme.nocrm.io/api/v2/leads", {}, MagicMock())
        assert total is None


class TestSourceResponse:
    def test_leads_partitions_on_created_at(self) -> None:
        response = nocrm_source(
            api_key="k", subdomain="acme", endpoint="leads", logger=MagicMock(), resumable_source_manager=MagicMock()
        )
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
        response = nocrm_source(
            api_key="k", subdomain="acme", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
