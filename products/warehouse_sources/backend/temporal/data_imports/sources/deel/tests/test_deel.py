import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel import (
    DeelResumeConfig,
    deel_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.settings import (
    DEEL_API_VERSION_2026_01_01,
    DEEL_API_VERSION_V2,
    DEEL_ENDPOINTS,
    ENDPOINTS,
    PAGE_SIZE,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the deel module.
DEEL_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel.make_tracked_session"

# (pin, base URL, version headers): the legacy pin sends no selector, the dated pin sends X-Version.
VERSION_WIRES = [
    (DEEL_API_VERSION_V2, "https://api.letsdeel.com/rest/v2", {}),
    (DEEL_API_VERSION_2026_01_01, "https://api.letsdeel.com/rest", {"X-Version": "2026-01-01"}),
]


def _response(items: list[dict[str, Any]] | None, *, cursor: str | None = None, drop_data: bool = False) -> Response:
    page: dict[str, Any] = {"total_rows": len(items or [])}
    if cursor is not None:
        page["cursor"] = cursor
    body: dict[str, Any] = {"page": page}
    if not drop_data:
        body["data"] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _wrapped_response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _payments_response(
    items: list[dict[str, Any]], *, next_cursor: str | None = None, has_more: bool = False
) -> Response:
    return _wrapped_response(
        {"data": {"rows": items, "has_more": has_more, "next_cursor": next_cursor, "total": len(items)}}
    )


def _time_offs_response(
    items: list[dict[str, Any]], *, next_token: str | None = None, has_next: bool = False
) -> Response:
    return _wrapped_response({"data": items, "next": next_token, "has_next_page": has_next})


def _payroll_response(
    items: list[dict[str, Any]], *, next_cursor: str | None = None, has_more: bool = False
) -> Response:
    # Payroll cycles and gross-to-net put both the cursor and the flag at the top level.
    return _wrapped_response({"data": items, "has_more": has_more, "next_cursor": next_cursor})


def _make_manager(resume_state: DeelResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire_capture(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session and capture each request's params and URL AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy
    when each request is prepared instead of inspecting the final state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    urls: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        urls.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, urls


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    params, _urls = _wire_capture(session, responses)
    return params


def _source(endpoint: str, manager: mock.MagicMock, api_version: str = DEEL_API_VERSION_V2):
    return deel_source(
        "token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, api_version=api_version
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, (True, None)),
            # A valid token without people:read still 403s; only 401 means the token is bad.
            (403, (True, None)),
            (401, (False, "Invalid Deel API token")),
        ],
    )
    @mock.patch(DEEL_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("token", DEEL_API_VERSION_V2) == expected

    @pytest.mark.parametrize("api_version, base_url, version_headers", VERSION_WIRES)
    @mock.patch(DEEL_SESSION_PATCH)
    def test_validate_credentials_probes_on_the_pinned_version(
        self, mock_session, api_version, base_url, version_headers
    ):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("token", api_version)

        call = mock_session.return_value.get.call_args
        assert call.args[0] == f"{base_url}/people?limit=1"
        assert call.kwargs["headers"] == {"Authorization": "Bearer token", **version_headers}

    @mock.patch(DEEL_SESSION_PATCH)
    def test_validate_credentials_reports_network_error_distinctly(self, mock_session):
        # A transient network failure must not masquerade as a bad token.
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        valid, error = validate_credentials("token", DEEL_API_VERSION_V2)
        assert valid is False
        assert error is not None and error.startswith("Could not reach Deel")


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession):
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(full_page), _response([{"id": "last"}])])

        manager = _make_manager()
        rows = _rows(_source("people", manager))

        assert [r["id"] for r in rows] == [*(str(i) for i in range(PAGE_SIZE)), "last"]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE
        # Checkpoint saved once after the first full page; the short page ends the walk.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == DeelResumeConfig(offset=PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response([])])

        manager = _make_manager(DeelResumeConfig(offset=150))
        _rows(_source("people", manager))

        assert params[0]["offset"] == 150

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_stops_without_saving_state(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source("people", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_is_lenient_empty_page(self, MockSession):
        # Deel's hand-rolled walk used `body.get("data", [])`, so a body without `data`
        # is a zero-row page, not a hard failure.
        session = MockSession.return_value
        _wire(session, [_response(None, drop_data=True)])

        manager = _make_manager()
        rows = _rows(_source("people", manager))

        assert rows == []
        manager.save_state.assert_not_called()


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_after_cursor(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}], cursor="cur_abc"), _response([{"id": "2"}])])

        manager = _make_manager()
        rows = _rows(_source("contracts", manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert params[0]["limit"] == PAGE_SIZE
        assert "after_cursor" not in params[0]
        assert params[1]["after_cursor"] == "cur_abc"
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == DeelResumeConfig(cursor="cur_abc")

    @pytest.mark.parametrize("num_pages", [2, 3])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_each_non_terminal_page(self, MockSession, num_pages):
        # Pages 1..n-1 carry a cursor; the terminal page has none, so state is saved
        # exactly n - 1 times — once after every page that advances the walk.
        session = MockSession.return_value
        responses = [_response([{"id": str(i)}], cursor=f"cur_{i}") for i in range(1, num_pages)]
        responses.append(_response([{"id": str(num_pages)}]))
        _wire(session, responses)

        manager = _make_manager()
        _rows(_source("contracts", manager))

        assert manager.save_state.call_count == num_pages - 1
        saved_cursors = [call.args[0].cursor for call in manager.save_state.call_args_list]
        assert saved_cursors == [f"cur_{i}" for i in range(1, num_pages)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response([])])

        manager = _make_manager(DeelResumeConfig(cursor="cur_resume"))
        _rows(_source("contracts", manager))

        assert params[0]["after_cursor"] == "cur_resume"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_with_cursor_stops(self, MockSession):
        # A cursor echoed alongside an empty page must terminate rather than loop.
        session = MockSession.return_value
        _wire(session, [_response([], cursor="cur_loop")])

        manager = _make_manager()
        rows = _rows(_source("contracts", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestDeelSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = DEEL_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(DEEL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"


class TestPaymentsPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_data_rows_until_has_more_is_false(self, MockSession):
        # Payments nest their rows and cursor under `data`, unlike every other Deel endpoint.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _payments_response([{"id": "p1"}], next_cursor="cur_1", has_more=True),
                _payments_response([{"id": "p2"}], next_cursor="cur_2", has_more=False),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("payments", manager))

        assert [r["id"] for r in rows] == ["p1", "p2"]
        # /payments takes no page-size param, so sending one would be undocumented.
        assert "limit" not in params[0]
        assert "cursor" not in params[0]
        assert params[1]["cursor"] == "cur_1"
        assert manager.save_state.call_args_list == [mock.call(DeelResumeConfig(cursor="cur_1"))]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_has_more_is_false_despite_an_echoed_cursor(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_payments_response([{"id": "p1"}], next_cursor="cur_stale", has_more=False)])

        manager = _make_manager()
        rows = _rows(_source("payments", manager))

        assert [r["id"] for r in rows] == ["p1"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_has_more_is_true_but_the_cursor_is_unchanged(self, MockSession):
        # A buggy or exhausted keyset can echo the same cursor back while still claiming
        # more pages exist. Without an equality check the walk would re-request that page
        # forever instead of stopping.
        session = MockSession.return_value
        _wire(
            session,
            [
                _payments_response([{"id": "p1"}], next_cursor="cur_1", has_more=True),
                _payments_response([{"id": "p1"}], next_cursor="cur_1", has_more=True),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("payments", manager))

        assert [r["id"] for r in rows] == ["p1", "p1"]
        assert session.send.call_count == 2
        manager.save_state.assert_called_once_with(DeelResumeConfig(cursor="cur_1"))


class TestTimeOffsPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_next_token_with_page_size_param(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _time_offs_response([{"id": "t1"}], next_token="tok_1", has_next=True),
                _time_offs_response([{"id": "t2"}], has_next=False),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("time_offs", manager))

        assert [r["id"] for r in rows] == ["t1", "t2"]
        # Time off sizes pages with `page_size`, not `limit`.
        assert params[0]["page_size"] == PAGE_SIZE
        assert "limit" not in params[0]
        assert params[1]["next"] == "tok_1"


class TestLegalEntitiesPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_cursor_param_and_explicit_sort_order(self, MockSession):
        # Legal entities page on `cursor`, not the `after_cursor` contracts use.
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "le1"}], cursor="cur_le"), _response([{"id": "le2"}])])

        manager = _make_manager()
        rows = _rows(_source("legal_entities", manager))

        assert [r["id"] for r in rows] == ["le1", "le2"]
        assert params[0]["sort_order"] == "ASC"
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["cursor"] == "cur_le"
        assert "after_cursor" not in params[1]


class TestFanoutEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_payment_breakdowns_carry_their_payment_id(self, MockSession):
        session = MockSession.return_value
        _params, urls = _wire_capture(
            session,
            [
                _payments_response([{"id": "pay_1"}, {"id": "pay_2"}]),
                _wrapped_response({"data": [{"contract_id": "c1", "invoice_id": "i1"}]}),
                _wrapped_response({"data": [{"contract_id": "c2", "invoice_id": "i2"}]}),
            ],
        )

        rows = _rows(_source("payment_breakdowns", _make_manager()))

        assert urls[1:] == [
            "https://api.letsdeel.com/rest/v2/payments/pay_1/breakdown",
            "https://api.letsdeel.com/rest/v2/payments/pay_2/breakdown",
        ]
        # The parent id is renamed off `_payments_id` because it is part of the primary key.
        assert [(r["payment_id"], r["contract_id"]) for r in rows] == [("pay_1", "c1"), ("pay_2", "c2")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cost_centers_carry_their_legal_entity_id(self, MockSession):
        session = MockSession.return_value
        _params, urls = _wire_capture(
            session,
            [
                _response([{"id": "le_1"}]),
                _wrapped_response({"data": [{"id": 7, "cost_center_name": "R&D"}]}),
            ],
        )

        rows = _rows(_source("cost_centers", _make_manager()))

        assert urls[1] == "https://api.letsdeel.com/rest/v2/legal-entities/le_1/cost-centers"

        assert rows == [{"id": 7, "cost_center_name": "R&D", "legal_entity_id": "le_1"}]


class TestTimeOffEvents:
    @pytest.mark.parametrize("api_version, base_url, version_headers", VERSION_WIRES)
    @mock.patch(DEEL_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_people_by_query_param(
        self, MockClientSession, MockDeelSession, api_version, base_url, version_headers
    ):
        _wire(MockClientSession.return_value, [_response([{"id": "prof_1"}, {"id": "prof_2"}])])
        child_session = MockDeelSession.return_value
        child_session.get.side_effect = [
            _wrapped_response({"data": [{"id": "ev_1", "hris_profile_id": "prof_1"}]}),
            _wrapped_response({"data": [{"id": "ev_2"}]}),
        ]

        rows = _rows(_source("time_off_events", _make_manager(), api_version))

        assert [call.args[0] for call in child_session.get.call_args_list] == [
            f"{base_url}/time_offs/time-off-events"
        ] * 2
        assert all(
            call.kwargs["headers"].get("X-Version") == version_headers.get("X-Version")
            for call in child_session.get.call_args_list
        )
        assert [call.kwargs["params"]["hris_profile_id"] for call in child_session.get.call_args_list] == [
            "prof_1",
            "prof_2",
        ]
        # Deel omits hris_profile_id from some rows; it is half the primary key, so backfill it.
        assert [(r["id"], r["hris_profile_id"]) for r in rows] == [("ev_1", "prof_1"), ("ev_2", "prof_2")]

    @mock.patch(DEEL_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_skips_a_person_that_disappeared_between_the_listing_and_the_fetch(
        self, MockClientSession, MockDeelSession
    ):
        _wire(MockClientSession.return_value, [_response([{"id": "prof_1"}, {"id": "prof_2"}])])
        gone = Response()
        gone.status_code = 404
        gone._content = b"{}"
        MockDeelSession.return_value.get.side_effect = [
            gone,
            _wrapped_response({"data": [{"id": "ev_2", "hris_profile_id": "prof_2"}]}),
        ]

        rows = _rows(_source("time_off_events", _make_manager()))

        assert [r["id"] for r in rows] == ["ev_2"]


class TestTrackerEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_offboarding_asks_for_every_termination(self, MockSession):
        # Deel defaults the offboarding tracker to the last 45 days; without this the table
        # silently loses every older leaver.
        session = MockSession.return_value
        params = _wire(session, [_response([{"unique_id": "off_1"}])])

        rows = _rows(_source("offboarding_tracker", _make_manager()))

        assert [r["unique_id"] for r in rows] == ["off_1"]
        assert params[0]["ignore_date_range"] == "true"
        assert params[0]["sort_order"] == "ASC"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_onboarding_pages_on_cursor(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session, [_response([{"unique_id": "on_1"}], cursor="cur_1"), _response([{"unique_id": "on_2"}])]
        )

        rows = _rows(_source("onboarding_tracker", _make_manager()))

        assert [r["unique_id"] for r in rows] == ["on_1", "on_2"]
        assert "ignore_date_range" not in params[0]
        assert params[1]["cursor"] == "cur_1"


class TestLookupEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_job_titles_page_on_after_cursor_without_a_page_size(self, MockSession):
        session = MockSession.return_value
        # Deel echoes a cursor past the last page, so the empty page is what ends the walk.
        params = _wire(
            session,
            [_response([{"id": 1}], cursor="cur_1"), _response([], cursor="cur_2")],
        )

        rows = _rows(_source("job_titles", _make_manager()))

        assert [r["id"] for r in rows] == [1]
        assert "limit" not in params[0]
        assert params[1]["after_cursor"] == "cur_1"
        assert session.send.call_count == 2

    @pytest.mark.parametrize(
        "endpoint, path",
        [
            ("departments", "/departments"),
            ("teams", "/teams"),
            ("countries", "/lookups/countries"),
            ("currencies", "/lookups/currencies"),
            ("seniorities", "/lookups/seniorities"),
        ],
    )
    @pytest.mark.parametrize("api_version, base_url, version_headers", VERSION_WIRES)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_lookups_send_one_request_with_no_page_size(
        self, MockSession, api_version, base_url, version_headers, endpoint, path
    ):
        session = MockSession.return_value
        params, urls = _wire_capture(session, [_response([{"code": "US"}])])

        _rows(_source(endpoint, _make_manager(), api_version))

        assert urls == [f"{base_url}{path}"]
        assert session.headers == version_headers
        assert params[0] == {}
        assert session.send.call_count == 1


class TestPayrollEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_payroll_cycles_fan_out_and_carry_their_legal_entity(self, MockSession):
        session = MockSession.return_value
        params, urls = _wire_capture(
            session,
            [
                _response([{"id": "le_1"}]),
                _payroll_response([{"id": "cy_1"}], next_cursor="cur_1", has_more=True),
                _payroll_response([{"id": "cy_2"}], has_more=False),
            ],
        )

        rows = _rows(_source("payroll_cycles", _make_manager()))

        assert urls[1:] == ["https://api.letsdeel.com/rest/v2/legal-entities/le_1/payroll-events"] * 2
        assert params[2]["cursor"] == "cur_1"
        assert params[1]["limit"] == PAGE_SIZE
        assert [(r["id"], r["legal_entity_id"]) for r in rows] == [("cy_1", "le_1"), ("cy_2", "le_1")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_payroll_reports_carry_their_legal_entity(self, MockSession):
        session = MockSession.return_value
        _params, urls = _wire_capture(
            session,
            [
                _response([{"id": "le_1"}]),
                _wrapped_response({"data": [{"id": "ev_1", "status": "CLOSED"}]}),
            ],
        )

        rows = _rows(_source("payroll_reports", _make_manager()))

        assert urls[1] == "https://api.letsdeel.com/rest/v2/gp/legal-entities/le_1/reports"
        assert rows == [{"id": "ev_1", "status": "CLOSED", "legal_entity_id": "le_1"}]


class TestGrossToNet:
    @pytest.mark.parametrize("api_version, base_url, version_headers", VERSION_WIRES)
    @mock.patch(DEEL_SESSION_PATCH)
    def test_walks_legal_entities_then_cycles_then_reports(self, MockSession, api_version, base_url, version_headers):
        session = MockSession.return_value
        session.get.side_effect = [
            _response([{"id": "le_1"}]),
            _payroll_response([{"id": "cy_1", "has_g2n_report": True}, {"id": "cy_2", "has_g2n_report": False}]),
            _payroll_response([{"contract_oid": "con_1"}]),
        ]

        manager = _make_manager()
        rows = _rows(_source("payroll_gross_to_net", manager, api_version))

        assert [call.args[0] for call in session.get.call_args_list] == [
            f"{base_url}/legal-entities",
            f"{base_url}/legal-entities/le_1/payroll-events",
            # cy_2 publishes no report, so it is never requested.
            f"{base_url}/reports/payroll/cycles/cy_1/gross-to-net",
        ]
        assert all(
            call.kwargs["headers"].get("X-Version") == version_headers.get("X-Version")
            for call in session.get.call_args_list
        )
        assert rows == [{"contract_oid": "con_1", "cycle_id": "cy_1", "legal_entity_id": "le_1"}]
        assert rows[0]["legal_entity_id"] == "le_1"
        # The cycle is checkpointed once its rows are out, so a resume skips it. A cycle id is
        # only unique within its legal entity, so the checkpoint carries both.
        manager.save_state.assert_called_once_with(DeelResumeConfig(completed=["le_1:cy_1"]))

    @mock.patch(DEEL_SESSION_PATCH)
    def test_resume_skips_cycles_already_emitted(self, MockSession):
        session = MockSession.return_value
        session.get.side_effect = [
            _response([{"id": "le_1"}]),
            _payroll_response([{"id": "cy_1", "has_g2n_report": True}, {"id": "cy_2", "has_g2n_report": True}]),
            _payroll_response([{"contract_oid": "con_2"}]),
        ]

        manager = _make_manager(DeelResumeConfig(completed=["le_1:cy_1"]))
        rows = _rows(_source("payroll_gross_to_net", manager))

        assert [call.args[0] for call in session.get.call_args_list][-1] == (
            "https://api.letsdeel.com/rest/v2/reports/payroll/cycles/cy_2/gross-to-net"
        )
        assert [r["cycle_id"] for r in rows] == ["cy_2"]
        assert manager.save_state.call_args.args[0] == DeelResumeConfig(completed=["le_1:cy_1", "le_1:cy_2"])

    @mock.patch(DEEL_SESSION_PATCH)
    def test_skips_a_cycle_whose_report_went_away(self, MockSession):
        # A cycle can flag a report that 404s by the time we ask for it; that must not fail
        # the whole sync.
        gone = Response()
        gone.status_code = 404
        gone._content = b"{}"
        session = MockSession.return_value
        session.get.side_effect = [
            _response([{"id": "le_1"}]),
            _payroll_response([{"id": "cy_1", "has_g2n_report": True}, {"id": "cy_2", "has_g2n_report": True}]),
            gone,
            _payroll_response([{"contract_oid": "con_2"}]),
        ]

        rows = _rows(_source("payroll_gross_to_net", _make_manager()))

        assert [r["contract_oid"] for r in rows] == ["con_2"]

    @mock.patch(DEEL_SESSION_PATCH)
    def test_stops_a_report_that_keeps_echoing_the_same_cursor(self, MockSession):
        session = MockSession.return_value
        session.get.side_effect = [
            _response([{"id": "le_1"}]),
            _payroll_response([{"id": "cy_1", "has_g2n_report": True}]),
            _payroll_response([{"contract_oid": "con_1"}], next_cursor="cur_1", has_more=True),
            _payroll_response([{"contract_oid": "con_1"}], next_cursor="cur_1", has_more=True),
        ]

        rows = _rows(_source("payroll_gross_to_net", _make_manager()))

        assert [r["contract_oid"] for r in rows] == ["con_1", "con_1"]
        assert session.get.call_count == 4


class TestDatedVersionEndpoints:
    @pytest.mark.parametrize(
        "endpoint, path, x_version, cursor_key, cursor_param, page_size_param, page_size, has_more_key",
        [
            ("it_seats", "/it/seats", "2026-09-25", "next_cursor", "cursor", "limit", 20, "has_more"),
            (
                "it_clearance_requests",
                "/it/clearance-requests",
                "2026-09-16",
                "next_cursor",
                "cursor",
                "limit",
                20,
                "has_more",
            ),
            (
                "time_off_policies",
                "/time-offs/policy",
                "2026-09-09",
                "next",
                "next",
                "page_size",
                PAGE_SIZE,
                "has_next_page",
            ),
            ("equity_awards", "/equity-awards", "2026-09-09", "next_cursor", "cursor", "limit", PAGE_SIZE, "has_more"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_on_the_endpoints_own_published_version(
        self, MockSession, endpoint, path, x_version, cursor_key, cursor_param, page_size_param, page_size, has_more_key
    ):
        # These endpoints were published after the 2026-01-01 baseline, and Deel rejects a date an
        # endpoint was not published under, so each one must send its own date.
        session = MockSession.return_value
        params, urls = _wire_capture(
            session,
            [
                _wrapped_response({"data": [{"id": "a"}], has_more_key: True, cursor_key: "cur_1"}),
                _wrapped_response({"data": [{"id": "b"}], has_more_key: False, cursor_key: None}),
            ],
        )

        rows = _rows(_source(endpoint, _make_manager(), DEEL_API_VERSION_2026_01_01))

        assert [r["id"] for r in rows] == ["a", "b"]
        assert urls == [f"https://api.letsdeel.com/rest{path}"] * 2
        assert session.headers == {"X-Version": x_version}
        assert params[0][page_size_param] == page_size
        assert params[1][cursor_param] == "cur_1"

    def test_an_undeclared_pin_fails_instead_of_sending_no_version(self):
        with pytest.raises(ValueError, match="Unsupported Deel API version"):
            _source("people", _make_manager(), "2099-01-01")
