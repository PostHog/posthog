import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import time_machine
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder import leadfeeder as leadfeeder_module
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder import (
    LEADFEEDER_BASE_URL,
    PAGE_SIZE,
    UNIFIED_MAX_PAGES,
    UNIFIED_OFFSET_LIMIT,
    UNIFIED_WINDOW_DAYS,
    LeadfeederResumeConfig,
    _default_start_date,
    _flatten_item,
    _to_date_str,
    _unified_client_config,
    _unified_headers,
    leadfeeder_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.settings import (
    LEADFEEDER_API_2026_08_07,
    LEADFEEDER_API_LEGACY,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the leadfeeder module.
LEADFEEDER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder.make_tracked_session"
)


def _item(id_: str, type_: str, **attributes: Any) -> dict[str, Any]:
    return {"id": id_, "type": type_, "attributes": attributes}


def _response(items: list[dict[str, Any]], next_url: str | None = None) -> Response:
    body: dict[str, Any] = {"data": items, "links": {"next": next_url} if next_url else {}}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: LeadfeederResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session, capturing the URL and params of each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared; the prepared mock also needs a real ``.url`` for the host-pinning check.
    """
    session.headers = {}
    urls: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        urls.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return urls, param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return leadfeeder_source("token", endpoint, manager, team_id=1, job_id="j", **kwargs)


def _unified_response(items: list[dict[str, Any]], page_count: int = 1) -> Response:
    # The unified API reports the last page under `meta.page_count`; a single page stops pagination.
    body: dict[str, Any] = {"data": items, "meta": {"page_num": 1, "page_count": page_count, "total_count": len(items)}}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _wire_full(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session, snapshotting each request's method, url, params, and json body."""
    session.headers = {}
    requests: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        requests.append(
            {
                "method": request.method,
                "url": request.url,
                "params": dict(request.params or {}),
                "json": request.json,
            }
        )
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return requests


class TestFlattenItem:
    def test_lifts_attributes_and_keeps_id_type(self) -> None:
        row = _flatten_item(_item("1", "leads", name="Acme", last_visit_date="2024-06-01"), account_id=None)
        assert row == {"id": "1", "type": "leads", "name": "Acme", "last_visit_date": "2024-06-01"}

    def test_injects_account_id_for_fan_out(self) -> None:
        row = _flatten_item(_item("9", "visits", started_at="2024-06-01T10:00:00Z"), account_id="42")
        assert row["account_id"] == "42"
        assert row["id"] == "9"

    def test_handles_missing_attributes(self) -> None:
        assert _flatten_item({"id": "1", "type": "accounts"}, account_id=None) == {"id": "1", "type": "accounts"}

    def test_missing_id_fails_loudly(self) -> None:
        # `id` is the primary key: a missing one must raise rather than seed a row under a None key.
        with pytest.raises(KeyError):
            _flatten_item({"type": "leads", "attributes": {"name": "Acme"}}, account_id="1")


class TestToDateStr:
    @parameterized.expand(
        [
            (datetime(2024, 6, 1, 15, 30, tzinfo=UTC), "2024-06-01"),
            (date(2024, 6, 1), "2024-06-01"),
            ("2024-06-01T09:00:00Z", "2024-06-01"),
            ("2024-06-01", "2024-06-01"),
        ]
    )
    def test_coerces_to_day_granular_string(self, value: Any, expected: str) -> None:
        assert _to_date_str(value) == expected


class TestDefaultStartDate:
    @time_machine.travel("2026-07-02", tick=False)
    def test_uses_config_start_date_floored(self) -> None:
        assert _default_start_date("2023-01-01T12:00:00Z") == "2023-01-01"

    @time_machine.travel("2026-07-02", tick=False)
    def test_defaults_to_lookback_window_when_blank(self) -> None:
        assert _default_start_date("") == "2025-07-02"


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_link_and_saves_state_after_batch(self, MockSession) -> None:
        session = MockSession.return_value
        page2_url = f"{LEADFEEDER_BASE_URL}/accounts?page[number]=2&page[size]=100"
        urls, _ = _wire(
            session,
            [
                _response([_item("1", "accounts", name="A")], next_url=page2_url),
                _response([_item("2", "accounts", name="B")]),
            ],
        )
        manager = _make_manager()
        rows = _rows(_source("accounts", manager))

        assert rows == [
            {"id": "1", "type": "accounts", "name": "A"},
            {"id": "2", "type": "accounts", "name": "B"},
        ]
        # State is saved once, pointing at the next page, only while a next link remains.
        manager.save_state.assert_called_once_with(LeadfeederResumeConfig(next_url=page2_url))
        # The second page is fetched from the URL the API handed back.
        assert urls[1] == page2_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = f"{LEADFEEDER_BASE_URL}/accounts?page[number]=5&page[size]=100"
        urls, _ = _wire(session, [_response([_item("7", "accounts")])])
        manager = _make_manager(LeadfeederResumeConfig(next_url=resume_url))

        _rows(_source("accounts", manager))
        assert urls[0] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_nothing_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])
        manager = _make_manager()

        assert _rows(_source("accounts", manager)) == []
        manager.save_state.assert_not_called()


class TestFanOut:
    def _accounts_response(self, *ids: str, next_url: str | None = None) -> Response:
        return _response([_item(i, "accounts") for i in ids], next_url=next_url)

    @mock.patch(CLIENT_SESSION_PATCH)
    @time_machine.travel("2026-07-02", tick=False)
    def test_iterates_every_account_and_injects_account_id(self, MockSession) -> None:
        session = MockSession.return_value
        urls, params = _wire(
            session,
            [
                self._accounts_response("1", "2"),
                _response([_item("100", "leads", name="Acme")]),
                _response([_item("200", "leads", name="Globex")]),
            ],
        )
        rows = _rows(_source("leads", _make_manager(), start_date_config="2024-01-01"))

        assert rows == [
            {"id": "100", "type": "leads", "name": "Acme", "account_id": "1"},
            {"id": "200", "type": "leads", "name": "Globex", "account_id": "2"},
        ]
        # Each account is fetched at its own fan-out path.
        assert any("/accounts/1/leads" in u for u in urls)
        assert any("/accounts/2/leads" in u for u in urls)
        # The lead request carries the server-side date-range filter.
        lead_params = next(p for p in params if "start_date" in p)
        assert lead_params["start_date"] == "2024-01-01"
        assert lead_params["end_date"] == "2026-07-02"

    @mock.patch(CLIENT_SESSION_PATCH)
    @time_machine.travel("2026-07-02", tick=False)
    def test_incremental_watermark_sets_start_date(self, MockSession) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [self._accounts_response("1"), _response([_item("100", "leads")])])

        rows = _rows(
            _source(
                "leads",
                _make_manager(),
                start_date_config="2020-01-01",
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2024, 5, 1),
            )
        )
        assert rows == [{"id": "100", "type": "leads", "account_id": "1"}]
        lead_params = next(p for p in params if "start_date" in p)
        # The watermark wins over the configured start date, floored to a day.
        assert lead_params["start_date"] == "2024-05-01"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_accounts(self, MockSession) -> None:
        session = MockSession.return_value
        urls, _ = _wire(session, [self._accounts_response("1", "2"), _response([_item("200", "leads")])])
        manager = _make_manager(
            LeadfeederResumeConfig(
                fanout_state={"completed": ["/accounts/1/leads"], "current": None, "child_state": None}
            )
        )
        rows = _rows(_source("leads", manager))

        assert rows == [{"id": "200", "type": "leads", "account_id": "2"}]
        assert not any("/accounts/1/leads" in u for u in urls)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unknown_completed_account_does_not_wedge_sync(self, MockSession) -> None:
        # A completed path for an account that no longer exists must not stop the remaining accounts.
        session = MockSession.return_value
        _wire(session, [self._accounts_response("1"), _response([_item("100", "leads")])])
        manager = _make_manager(
            LeadfeederResumeConfig(
                fanout_state={"completed": ["/accounts/999/leads"], "current": None, "child_state": None}
            )
        )
        assert _rows(_source("leads", manager)) == [{"id": "100", "type": "leads", "account_id": "1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_old_shape_resume_starts_fresh(self, MockSession) -> None:
        # A pre-migration state (account_id/next_url, no fanout_state) still parses and starts fresh.
        session = MockSession.return_value
        urls, _ = _wire(
            session,
            [self._accounts_response("1", "2"), _response([_item("100", "leads")]), _response([_item("200", "leads")])],
        )
        manager = _make_manager(LeadfeederResumeConfig(account_id="2", next_url=None))
        rows = _rows(_source("leads", manager))

        assert {r["account_id"] for r in rows} == {"1", "2"}
        assert any("/accounts/1/leads" in u for u in urls)


class TestSourceResponse:
    def test_accounts_is_full_refresh_without_partitioning(self) -> None:
        response = _source("accounts", _make_manager())
        assert response.name == "accounts"
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None

    @parameterized.expand(
        [
            ("leads", ["account_id", "id"], "first_visit_date"),
            ("visits", ["account_id", "id"], "started_at"),
        ]
    )
    def test_fan_out_endpoints_have_composite_key_and_partition(
        self, endpoint: str, primary_keys: list[str], partition_key: str
    ) -> None:
        response = _source(endpoint, _make_manager())
        assert response.primary_keys == primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)])
    @mock.patch(LEADFEEDER_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("token") is expected

    @mock.patch(LEADFEEDER_SESSION_PATCH)
    def test_exception_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False

    @mock.patch(LEADFEEDER_SESSION_PATCH)
    def test_sends_token_auth_header(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("secret")
        assert mock_session.return_value.get.call_args.kwargs["headers"]["Authorization"] == "Token token=secret"

    @mock.patch(LEADFEEDER_SESSION_PATCH)
    def test_session_redacts_token_and_blocks_redirects(self, mock_session: mock.MagicMock) -> None:
        # The token rides in a custom `Authorization: Token token=...` header the denylist can't see,
        # so it must be registered for value-based redaction; redirects must not be followed or the
        # credentialed request could resend the token off-origin.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("secret")
        assert mock_session.call_args.kwargs["redact_values"] == ("secret",)
        assert mock_session.call_args.kwargs["allow_redirects"] is False

    @mock.patch(LEADFEEDER_SESSION_PATCH)
    def test_unified_probe_uses_api_key_header_on_v1_accounts(self, mock_session: mock.MagicMock) -> None:
        # A source pinned to the unified API must probe `/v1/accounts` with an `X-Api-Key` header,
        # not the legacy `Authorization: Token` header on `/accounts`.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("secret", LEADFEEDER_API_2026_08_07)
        call = mock_session.return_value.get.call_args
        assert (call.args[0] if call.args else call.kwargs["url"]) == f"{LEADFEEDER_BASE_URL}/v1/accounts"
        assert call.kwargs["headers"]["X-Api-Key"] == "secret"
        assert "Authorization" not in call.kwargs["headers"]


class TestUnifiedClientConfig:
    def test_client_config_sends_api_key_header_and_page_number_pagination(self) -> None:
        client = _unified_client_config("key123")
        assert client["base_url"] == LEADFEEDER_BASE_URL
        assert client["auth"] == {"type": "api_key", "api_key": "key123", "name": "X-Api-Key", "location": "header"}
        paginator = client["paginator"]
        assert isinstance(paginator, PageNumberPaginator)
        assert paginator.page_param == "page[num]"

    def test_headers_carry_api_key(self) -> None:
        assert _unified_headers("key123")["X-Api-Key"] == "key123"


class TestUnifiedRequests:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_accounts_hits_v1_path_with_page_params(self, MockSession) -> None:
        session = MockSession.return_value
        requests = _wire_full(session, [_unified_response([_item("1", "account", name="A")])])
        rows = _rows(_source("accounts", _make_manager(), api_version=LEADFEEDER_API_2026_08_07))

        assert rows == [{"id": "1", "type": "account", "name": "A"}]
        assert requests[0]["url"] == f"{LEADFEEDER_BASE_URL}/v1/accounts"
        assert requests[0]["params"]["page[num]"] == 1
        assert requests[0]["params"]["page[size]"] == 100

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_accounts_pagination_stops_without_meta_page_count(self, MockSession) -> None:
        # The real /v1/accounts endpoint returns its whole result set in one response with no
        # `meta.page_count` field at all (unlike the paginated child endpoints, modelled by
        # _unified_response). The client-level PageNumberPaginator's total-pages stop check silently
        # no-ops when that field is missing, and the page is never empty either, so it would otherwise
        # keep requesting page[num]=2, 3, ... forever. Accounts must use a paginator that always stops
        # after a single page regardless of what the response body contains.
        session = MockSession.return_value
        body = {"data": [{"id": "1", "type": "account", "attributes": {}}]}
        resp = Response()
        resp.status_code = 200
        resp._content = json.dumps(body).encode()
        requests = _wire_full(session, [resp])

        rows = _rows(_source("accounts", _make_manager(), api_version=LEADFEEDER_API_2026_08_07))

        assert rows == [{"id": "1", "type": "account"}]
        assert len(requests) == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    @time_machine.travel("2026-07-02", tick=False)
    def test_leads_fan_out_hits_visitor_companies_with_account_id_query(self, MockSession) -> None:
        session = MockSession.return_value
        requests = _wire_full(
            session,
            [
                _unified_response([_item("1", "account"), _item("2", "account")]),
                _unified_response([_item("100", "company_location")]),
                _unified_response([_item("200", "company_location")]),
            ],
        )
        _rows(_source("leads", _make_manager(), start_date_config="2026-06-15", api_version=LEADFEEDER_API_2026_08_07))

        company_reqs = [r for r in requests if "/v1/web-visits/companies" in r["url"]]
        # account id is a query param on the unified API (a path segment on the legacy API).
        assert {r["params"]["account_id"] for r in company_reqs} == {"1", "2"}
        assert company_reqs[0]["params"]["start_date"] == "2026-06-15"
        assert company_reqs[0]["params"]["end_date"] == "2026-07-02"

    @mock.patch(CLIENT_SESSION_PATCH)
    @time_machine.travel("2026-07-02", tick=False)
    def test_visits_fan_out_posts_web_visits_with_date_body(self, MockSession) -> None:
        session = MockSession.return_value
        requests = _wire_full(
            session,
            [
                _unified_response([_item("1", "account")]),
                _unified_response([_item("100", "web_visit", started_at="2026-06-01T10:00:00Z")]),
            ],
        )
        _rows(_source("visits", _make_manager(), start_date_config="2026-06-15", api_version=LEADFEEDER_API_2026_08_07))

        visit_reqs = [r for r in requests if r["url"].endswith("/v1/web-visits")]
        assert visit_reqs, "expected a request to the unified web-visits search"
        # The web-visits search is a POST carrying its date window in the body, not the query string.
        assert visit_reqs[0]["method"] == "POST"
        assert visit_reqs[0]["json"] == {"start_date": "2026-06-15", "end_date": "2026-07-02"}
        assert visit_reqs[0]["params"]["account_id"] == "1"

    @parameterized.expand(
        [
            ("configured_start_date", {"start_date_config": "2026-09-01"}),
            ("incremental_watermark", {"db_incremental_field_last_value": datetime(2026, 9, 1, tzinfo=UTC)}),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    @time_machine.travel("2026-07-02", tick=False)
    def test_future_start_is_clamped_to_today_instead_of_syncing_nothing(
        self, _name: str, source_kwargs: dict[str, Any], MockSession
    ) -> None:
        # A start after today inverts the range, so the window split yields no window at all and the
        # sync reports success without asking the vendor for a single row.
        session = MockSession.return_value
        requests = _wire_full(
            session,
            [
                _unified_response([_item("1", "account")]),
                _unified_response([_item("100", "company_location")]),
            ],
        )
        rows = _rows(_source("leads", _make_manager(), api_version=LEADFEEDER_API_2026_08_07, **source_kwargs))

        company_reqs = [r for r in requests if "/v1/web-visits/companies" in r["url"]]
        assert [(r["params"]["start_date"], r["params"]["end_date"]) for r in company_reqs] == [
            ("2026-07-02", "2026-07-02")
        ]
        assert [row["id"] for row in rows] == ["100"]


class TestUnifiedOffsetLimit:
    def test_page_cap_keeps_every_requested_page_inside_the_vendor_offset_limit(self) -> None:
        # Page UNIFIED_MAX_PAGES reads rows up to offset UNIFIED_MAX_PAGES * PAGE_SIZE - 1. One page
        # more and the vendor answers 416 `offset_exceeded`, which is not retryable and fails the import.
        assert UNIFIED_MAX_PAGES * PAGE_SIZE <= UNIFIED_OFFSET_LIMIT
        paginator = _unified_client_config("key")["paginator"]
        assert isinstance(paginator, PageNumberPaginator)
        assert paginator.maximum_page == UNIFIED_MAX_PAGES

    @mock.patch(CLIENT_SESSION_PATCH)
    @time_machine.travel("2026-07-02", tick=False)
    def test_sync_window_is_chunked_into_contiguous_windows(self, MockSession) -> None:
        # A first sync spans up to a year, far more than the offset limit can page through in one
        # request, so the window is split before the vendor ever sees an out-of-range offset.
        session = MockSession.return_value
        requests = _wire_full(
            session,
            [_unified_response([_item("1", "account")])] + [_unified_response([]) for _ in range(40)],
        )
        _rows(_source("leads", _make_manager(), start_date_config="2026-01-01", api_version=LEADFEEDER_API_2026_08_07))

        windows = [
            (date.fromisoformat(r["params"]["start_date"]), date.fromisoformat(r["params"]["end_date"]))
            for r in requests
            if "/v1/web-visits/companies" in r["url"]
        ]
        assert len(windows) > 1
        assert windows[0][0] == date(2026, 1, 1)
        assert windows[-1][1] == date(2026, 7, 2)
        for (_, previous_end), (next_start, next_end) in zip(windows, windows[1:]):
            assert next_start == previous_end + timedelta(days=1)
            assert (next_end - next_start).days < UNIFIED_WINDOW_DAYS

    @mock.patch(CLIENT_SESSION_PATCH)
    @time_machine.travel("2026-07-02", tick=False)
    @mock.patch.multiple(
        "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder",
        UNIFIED_OFFSET_LIMIT=4,
        UNIFIED_MAX_PAGES=2,
    )
    def test_window_truncated_by_the_page_cap_is_halved_and_re_read(self, MockSession) -> None:
        # The cap alone would drop every row past it without a word. A window that comes back full is
        # read again in halves, which merge dedupes on the primary key.
        session = MockSession.return_value
        requests = _wire_full(
            session,
            [
                _unified_response([_item("1", "account")]),
                _unified_response([_item("100", "company_location"), _item("101", "company_location")], page_count=9),
                _unified_response([_item("102", "company_location"), _item("103", "company_location")], page_count=9),
                _unified_response([_item("104", "company_location")]),
                _unified_response([_item("105", "company_location")]),
            ],
        )
        rows = _rows(
            _source("leads", _make_manager(), start_date_config="2026-06-29", api_version=LEADFEEDER_API_2026_08_07)
        )

        company_reqs = [r for r in requests if "/v1/web-visits/companies" in r["url"]]
        # Two capped pages of the full window, then one request per half.
        assert [r["params"]["page[num]"] for r in company_reqs] == [1, 2, 1, 1]
        assert [(r["params"]["start_date"], r["params"]["end_date"]) for r in company_reqs[2:]] == [
            ("2026-06-29", "2026-06-30"),
            ("2026-07-01", "2026-07-02"),
        ]
        assert [row["id"] for row in rows] == ["100", "101", "102", "103", "104", "105"]

    @mock.patch(CLIENT_SESSION_PATCH)
    @time_machine.travel("2026-07-02", tick=False)
    @mock.patch.multiple(
        "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder",
        UNIFIED_OFFSET_LIMIT=2,
        UNIFIED_MAX_PAGES=1,
    )
    def test_single_day_over_the_offset_limit_warns_instead_of_truncating_silently(self, MockSession) -> None:
        session = MockSession.return_value
        _wire_full(
            session,
            [
                _unified_response([_item("1", "account")]),
                _unified_response([_item("100", "company_location"), _item("101", "company_location")], page_count=9),
            ],
        )
        with mock.patch.object(leadfeeder_module.logger, "warning") as warning:
            _rows(
                _source("leads", _make_manager(), start_date_config="2026-07-02", api_version=LEADFEEDER_API_2026_08_07)
            )

        assert warning.call_count == 1
        assert warning.call_args.kwargs["extra"] == {"account_id": "1", "day": "2026-07-02"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_legacy_pin_still_uses_token_api_paths(self, MockSession) -> None:
        # The legacy request path must be unchanged for sources still pinned to it.
        session = MockSession.return_value
        requests = _wire_full(session, [_response([_item("1", "accounts", name="A")])])
        _rows(_source("accounts", _make_manager(), api_version=LEADFEEDER_API_LEGACY))

        assert requests[0]["url"] == f"{LEADFEEDER_BASE_URL}/accounts"
        assert requests[0]["params"]["page[number]"] == 1
