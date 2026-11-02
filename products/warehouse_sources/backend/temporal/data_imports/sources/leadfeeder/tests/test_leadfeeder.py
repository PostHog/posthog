import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from parameterized import parameterized
from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.leadfeeder import (
    LeadfeederSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder import (
    LEADFEEDER_BASE_URL,
    LeadfeederResumeConfig,
    _flatten_item,
    _is_offset_exceeded,
    _split_window,
    _to_date_str,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.settings import (
    LEADFEEDER_API_2026_08_07,
    LEADFEEDER_API_LEGACY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.source import LeadfeederSource


def _item(id_: str, type_: str, **attributes: Any) -> dict[str, Any]:
    return {"id": id_, "type": type_, "attributes": attributes}


def _response(items: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items, "links": {"next": next_url} if next_url else {}}
    return ScriptedResponse(json=body)


def _driver(start_date: str | None = None) -> SourceDriver:
    return SourceDriver(LeadfeederSource(), LeadfeederSourceConfig(api_token="token", start_date=start_date))


def _unified_response(items: list[dict[str, Any]], page_count: int = 1) -> ScriptedResponse:
    # The unified API reports the last page under `meta.page_count`; a single page stops pagination.
    body: dict[str, Any] = {
        "data": items,
        "meta": {"page_num": 1, "page_count": page_count, "total_count": len(items)},
    }
    return ScriptedResponse(json=body)


class TestFlattenItem:
    def test_injects_account_id_for_fan_out(self) -> None:
        row = _flatten_item(_item("9", "visits", started_at="2024-06-01T10:00:00Z"), account_id="42")
        assert row["account_id"] == "42"
        assert row["id"] == "9"

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


class TestTopLevelPagination:
    def test_follows_next_link_and_saves_state_after_batch(self) -> None:
        page2_url = f"{LEADFEEDER_BASE_URL}/accounts?page[number]=2&page[size]=100"
        result = _driver().run(
            "accounts",
            [
                _response([_item("1", "accounts", name="A")], next_url=page2_url),
                _response([_item("2", "accounts", name="B")]),
            ],
            api_version=LEADFEEDER_API_LEGACY,
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "1", "type": "accounts", "name": "A"},
            {"id": "2", "type": "accounts", "name": "B"},
        ]
        # State is saved once, pointing at the next page, only while a next link remains.
        assert result.saved_states == [LeadfeederResumeConfig(next_url=page2_url)]
        # The second page is fetched from the URL the API handed back.
        assert result.requests[1].origin == LEADFEEDER_BASE_URL
        assert result.requests[1].path == "/accounts"
        assert result.requests[1].param("page[number]") == "2"

    def test_resumes_from_saved_next_url(self) -> None:
        resume_url = f"{LEADFEEDER_BASE_URL}/accounts?page[number]=5&page[size]=100"
        result = _driver().run(
            "accounts",
            [_response([_item("7", "accounts")])],
            resume_state=LeadfeederResumeConfig(next_url=resume_url),
            api_version=LEADFEEDER_API_LEGACY,
        )

        assert result.raised is None
        assert result.requests[0].origin == LEADFEEDER_BASE_URL
        assert result.requests[0].path == "/accounts"
        assert result.requests[0].param("page[number]") == "5"


class TestFanOut:
    def _accounts_response(self, *ids: str, next_url: str | None = None) -> ScriptedResponse:
        return _response([_item(i, "accounts") for i in ids], next_url=next_url)

    @time_machine.travel("2026-07-02", tick=False)
    def test_iterates_every_account_and_injects_account_id(self) -> None:
        result = _driver("2024-01-01").run(
            "leads",
            [
                self._accounts_response("1", "2"),
                _response([_item("100", "leads", name="Acme")]),
                _response([_item("200", "leads", name="Globex")]),
            ],
            api_version=LEADFEEDER_API_LEGACY,
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "100", "type": "leads", "name": "Acme", "account_id": "1"},
            {"id": "200", "type": "leads", "name": "Globex", "account_id": "2"},
        ]
        # Each account is fetched at its own fan-out path.
        assert "/accounts/1/leads" in result.paths
        assert "/accounts/2/leads" in result.paths
        # The lead request carries the server-side date-range filter.
        lead_request = next(request for request in result.requests if request.param("start_date") is not None)
        assert lead_request.param("start_date") == "2024-01-01"
        assert lead_request.param("end_date") == "2026-07-02"

    def test_old_shape_resume_starts_fresh(self) -> None:
        # A pre-migration state (account_id/next_url, no fanout_state) still parses and starts fresh.
        result = _driver().run(
            "leads",
            [
                self._accounts_response("1", "2"),
                _response([_item("100", "leads")]),
                _response([_item("200", "leads")]),
            ],
            resume_state=LeadfeederResumeConfig(account_id="2", next_url=None),
            api_version=LEADFEEDER_API_LEGACY,
        )

        assert result.raised is None
        assert {row["account_id"] for row in result.rows} == {"1", "2"}
        assert "/accounts/1/leads" in result.paths


def _unpaginated_unified_response(items: list[dict[str, Any]]) -> ScriptedResponse:
    # The unified custom-feeds list carries no `meta.page_count`, so only a single-page paginator stops it.
    return ScriptedResponse(json={"data": items, "meta": {"request_id": "req-1"}})


class TestCustomFeeds:
    @parameterized.expand(
        [
            (
                "legacy",
                LEADFEEDER_API_LEGACY,
                _response,
                ["/accounts", "/accounts/1/custom-feeds", "/accounts/2/custom-feeds"],
            ),
            (
                "unified",
                LEADFEEDER_API_2026_08_07,
                _unpaginated_unified_response,
                ["/v1/accounts", "/v1/web-visits/custom-feeds", "/v1/web-visits/custom-feeds"],
            ),
        ]
    )
    def test_reads_one_unwindowed_page_per_account(
        self, _name: str, api_version: str, feeds_response: Any, expected_paths: list[str]
    ) -> None:
        result = _driver("2024-01-01").run(
            "custom_feeds",
            [
                feeds_response([_item("1", "accounts"), _item("2", "accounts")]),
                feeds_response([_item("all_leads", "custom_feeds", name="All leads")]),
                feeds_response([_item("all_leads", "custom_feeds", name="All leads"), _item("77", "custom_feeds")]),
            ],
            api_version=api_version,
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "all_leads", "type": "custom_feeds", "name": "All leads", "account_id": "1"},
            {"id": "all_leads", "type": "custom_feeds", "name": "All leads", "account_id": "2"},
            {"id": "77", "type": "custom_feeds", "account_id": "2"},
        ]
        assert result.paths == expected_paths
        feed_requests = result.requests[1:]
        if api_version == LEADFEEDER_API_2026_08_07:
            assert [request.param("account_id") for request in feed_requests] == ["1", "2"]
        for request in feed_requests:
            for param in ("start_date", "end_date", "page[number]", "page[num]", "page[size]"):
                assert request.param(param) is None
        assert result.response is not None
        assert result.response.primary_keys == ["account_id", "id"]


class TestSourceResponse:
    @parameterized.expand(
        [
            ("leads", ["account_id", "id"], "first_visit_date"),
            ("visits", ["account_id", "id"], "started_at"),
        ]
    )
    def test_fan_out_endpoints_have_composite_key_and_partition(
        self, endpoint: str, primary_keys: list[str], partition_key: str
    ) -> None:
        response = _driver().run(endpoint, [_response([])], api_version=LEADFEEDER_API_LEGACY).response
        assert response is not None
        assert response.primary_keys == primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]


class TestValidateCredentials:
    def test_session_redacts_token_and_blocks_redirects(self) -> None:
        # The token rides in a custom `Authorization: Token token=...` header the denylist can't see,
        # so it must be registered for value-based redaction; redirects must not be followed or the
        # credentialed request could resend the token off-origin.
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("secret") is True
        assert network.session_options[0]["redact_values"] == ("secret",)
        assert network.session_options[0]["allow_redirects"] is False

    def test_unified_probe_uses_api_key_header_on_v1_accounts(self) -> None:
        # A source pinned to the unified API must probe `/v1/accounts` with an `X-Api-Key` header,
        # not the legacy `Authorization: Token` header on `/accounts`.
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("secret", LEADFEEDER_API_2026_08_07) is True
        request = network.requests_log[0]
        assert request.url == f"{LEADFEEDER_BASE_URL}/v1/accounts"
        assert request.headers["x-api-key"] == "secret"
        assert "authorization" not in request.headers


def _offset_exceeded_response(body: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(status=416, json=body)


def _http_error(status_code: int, body: dict[str, Any] | None) -> HTTPError:
    resp = Response()
    resp.status_code = status_code
    if body is not None:
        resp._content = json.dumps(body).encode()
    return HTTPError(response=resp)


class TestIsOffsetExceeded:
    @parameterized.expand(
        [
            ("top_level_code", {"code": "offset_exceeded"}),
            # A JSON:API error body wraps the code in an `errors` list.
            ("wrapped_in_errors", {"errors": [{"code": "offset_exceeded", "title": "Offset exceeded"}]}),
        ]
    )
    def test_matches_416_naming_the_code(self, _name: str, body: dict[str, Any]) -> None:
        assert _is_offset_exceeded(_http_error(416, body)) is True

    @parameterized.expand(
        [
            ("different_code_on_416", 416, {"code": "unauthorized"}),
            ("offset_exceeded_code_on_other_status", 404, {"code": "offset_exceeded"}),
            ("no_body", 416, None),
        ]
    )
    def test_does_not_match(self, _name: str, status_code: int, body: dict[str, Any] | None) -> None:
        assert _is_offset_exceeded(_http_error(status_code, body)) is False


class TestSplitWindow:
    @parameterized.expand(
        [
            (
                "two_days_in_halves",
                "2026-07-01",
                "2026-07-02",
                2,
                [("2026-07-01", "2026-07-01"), ("2026-07-02", "2026-07-02")],
            ),
            (
                "five_days_in_three",
                "2026-07-01",
                "2026-07-05",
                3,
                [("2026-07-01", "2026-07-02"), ("2026-07-03", "2026-07-04"), ("2026-07-05", "2026-07-05")],
            ),
            # Fewer than two parts would leave the window unchanged and recurse forever.
            (
                "one_part_still_splits",
                "2026-07-01",
                "2026-07-04",
                1,
                [("2026-07-01", "2026-07-02"), ("2026-07-03", "2026-07-04")],
            ),
        ]
    )
    def test_covers_the_window_without_gaps(
        self, _name: str, start: str, end: str, parts: int, expected: list[tuple[str, str]]
    ) -> None:
        assert [(window.start, window.end) for window in _split_window(start, end, parts)] == expected

    @parameterized.expand(
        [
            ("single_day", "2026-07-02", "2026-07-02", 4),
            ("end_before_start", "2026-07-02", "2026-07-01", 4),
            ("unparseable_bound", "01/07/2026", "2026-07-02", 4),
        ]
    )
    def test_returns_nothing_when_there_is_no_narrower_window(
        self, _name: str, start: str, end: str, parts: int
    ) -> None:
        assert _split_window(start, end, parts) == []


class TestUnifiedRequests:
    def test_accounts_hits_v1_path_with_page_params(self) -> None:
        result = _driver().run("accounts", [_unified_response([_item("1", "account", name="A")])])

        assert result.raised is None
        assert result.rows == [{"id": "1", "type": "account", "name": "A"}]
        assert result.paths == ["/v1/accounts"]
        assert result.requests[0].param("page[num]") == "1"
        assert result.requests[0].param("page[size]") == "100"

    @time_machine.travel("2026-07-02", tick=False)
    def test_visits_fan_out_posts_web_visits_with_date_body(self) -> None:
        result = _driver("2024-01-01").run(
            "visits",
            [
                _unified_response([_item("1", "account")]),
                _unified_response([], page_count=1),
                _unified_response([_item("100", "web_visit", started_at="2026-06-01T10:00:00Z")]),
            ],
        )

        assert result.raised is None
        visit_reqs = [request for request in result.requests if request.path == "/v1/web-visits"]
        assert visit_reqs, "expected a request to the unified web-visits search"
        # The web-visits search is a POST carrying its date window in the body, not the query string.
        assert visit_reqs[0].method == "POST"
        assert visit_reqs[0].json() == {"start_date": "2024-01-01", "end_date": "2026-07-02"}
        assert visit_reqs[0].param("account_id") == "1"

    @time_machine.travel("2026-07-02", tick=False)
    def test_window_reporting_more_pages_than_the_vendor_serves_is_split(self) -> None:
        # A busy account can hold more rows in the sync window than the vendor will page through:
        # past 100 pages of 100 it answers 416 `offset_exceeded` instead of the next page. The rows
        # past that point are only reachable through a narrower date window, so a window reporting
        # more pages than that must be split before any of it is read.
        result = _driver("2026-01-01").run(
            "leads",
            [
                _unified_response([_item("1", "account")]),
                _unified_response([], page_count=200),
                _unified_response([], page_count=1),
                _unified_response([_item("100", "company_location")]),
                _unified_response([], page_count=1),
                _unified_response([_item("200", "company_location")]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "100", "type": "company_location", "account_id": "1"},
            {"id": "200", "type": "company_location", "account_id": "1"},
        ]
        windows = [
            (request.param("start_date"), request.param("end_date"))
            for request in result.requests
            if request.path == "/v1/web-visits/companies"
        ]
        # The whole window is covered by halves, each read end to end, with no gap or overlap.
        assert windows[0] == ("2026-01-01", "2026-07-02")
        assert set(windows[1:]) == {("2026-01-01", "2026-04-02"), ("2026-04-03", "2026-07-02")}

    @time_machine.travel("2026-07-02", tick=False)
    def test_offset_exceeded_mid_window_re_reads_the_window_narrower(self) -> None:
        # The page count the vendor reports can understate what it will serve, so a window can still
        # run into the 416 half way through. The rest of that window must be re-read as narrower
        # windows; stopping there would silently drop every row past the limit.
        result = _driver("2026-07-01").run(
            "leads",
            [
                _unified_response([_item("1", "account")]),
                _unified_response([], page_count=1),
                _unified_response([_item("100", "company_location")], page_count=2),
                _offset_exceeded_response({"code": "offset_exceeded"}),
                _unified_response([], page_count=1),
                _unified_response([_item("200", "company_location")]),
                _unified_response([], page_count=1),
                _unified_response([_item("300", "company_location")]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["100", "200", "300"]
        windows = {
            (request.param("start_date"), request.param("end_date"))
            for request in result.requests
            if request.path == "/v1/web-visits/companies"
        }
        assert ("2026-07-01", "2026-07-01") in windows
        assert ("2026-07-02", "2026-07-02") in windows

    @time_machine.travel("2026-07-02", tick=False)
    def test_single_day_over_the_limit_keeps_the_rows_it_can_read(self) -> None:
        # A single day can hold more rows than the vendor will page through, and there is no
        # narrower window to ask for. Keep the rows that were read and finish the table instead of
        # splitting forever or failing the sync.
        result = _driver("2026-07-02").run(
            "leads",
            [
                _unified_response([_item("1", "account")]),
                _unified_response([], page_count=150),
                _unified_response([_item("100", "company_location")], page_count=150),
                _offset_exceeded_response({"code": "offset_exceeded"}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "100", "type": "company_location", "account_id": "1"}]
        assert len(result.requests) == 4
