import json
from datetime import date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.opencorporates import (
    OpencorporatesResumeConfig,
    _format_incremental_filter,
    opencorporates_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.settings import (
    OPENCORPORATES_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the opencorporates module.
OPENCORPORATES_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.opencorporates.make_tracked_session"


def _companies_page(companies: list[dict[str, Any]], *, page: int, total_pages: int) -> Response:
    return _response(
        {"results": {"companies": [{"company": c} for c in companies], "page": page, "total_pages": total_pages}}
    )


def _officers_page(officers: list[dict[str, Any]], *, drop_total_pages: bool = False) -> Response:
    results: dict[str, Any] = {"officers": [{"officer": o} for o in officers]}
    if not drop_total_pages:
        results["total_pages"] = 1
    return _response({"results": results})


def _response(body: Any, *, status: int = 200, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.opencorporates.com/v0.4/companies/search?api_token=supersecret&page=1"
    return resp


def _make_manager(resume_state: OpencorporatesResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(
    endpoint: str = "Companies",
    manager: mock.MagicMock | None = None,
    *,
    query: str = "acme",
    jurisdiction_code: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Any:
    return opencorporates_source(
        "supersecret",
        query,
        jurisdiction_code,
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager or _make_manager(),
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestCursorFormatting:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 4, 9, 12, 30), "2021-04-09:"),
            ("date", date(2021, 4, 9), "2021-04-09:"),
            ("iso_string", "2021-04-09T00:00:00+0000", "2021-04-09:"),
        ]
    )
    def test_format_incremental_filter(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_filter(value) == expected


class TestCompaniesPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_total_pages_reached(self, MockSession) -> None:
        session = MockSession.return_value
        page1 = [{"company_number": f"{i}", "jurisdiction_code": "gb"} for i in range(100)]
        page2 = [{"company_number": f"{i}", "jurisdiction_code": "gb"} for i in range(100, 150)]
        params = _wire(
            session,
            [_companies_page(page1, page=1, total_pages=2), _companies_page(page2, page=2, total_pages=2)],
        )

        rows = _rows(_source("Companies"))

        assert len(rows) == 150
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_first_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_companies_page([], page=1, total_pages=0)])

        assert _rows(_source("Companies")) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session, [_companies_page([{"company_number": "1", "jurisdiction_code": "gb"}], page=3, total_pages=3)]
        )

        _rows(_source("Companies", manager=_make_manager(OpencorporatesResumeConfig(next_page=3))))

        # The first request must start from the persisted page, not page 1.
        assert params[0]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding_a_page(self, MockSession) -> None:
        session = MockSession.return_value
        page1 = [{"company_number": f"{i}", "jurisdiction_code": "gb"} for i in range(100)]
        page2 = [{"company_number": f"{i}", "jurisdiction_code": "gb"} for i in range(100, 200)]
        _wire(
            session,
            [_companies_page(page1, page=1, total_pages=2), _companies_page(page2, page=2, total_pages=2)],
        )

        manager = _make_manager()
        _rows(_source("Companies", manager=manager))

        # State saved once, with the next page to resume from, only while more pages remain.
        manager.save_state.assert_called_once_with(OpencorporatesResumeConfig(next_page=2))


class TestOfficersPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_short_page_when_total_pages_missing(self, MockSession) -> None:
        # officers/search isn't confirmed to report `results.total_pages`; the base paginator's
        # stop_after_empty_page must still terminate cleanly.
        session = MockSession.return_value
        _wire(
            session,
            [
                _officers_page([{"id": "1", "name": "A"}], drop_total_pages=True),
                _officers_page([], drop_total_pages=True),
            ],
        )

        rows = _rows(_source("Officers"))

        assert len(rows) == 1
        assert session.send.call_count == 2


class TestRequestParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_omits_updated_at_and_order(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_companies_page([], page=1, total_pages=0)])

        _rows(_source("Companies", query="acme", should_use_incremental_field=False))

        assert params[0]["q"] == "acme"
        assert params[0]["per_page"] == 100
        assert "updated_at" not in params[0]
        assert "order" not in params[0]
        assert "jurisdiction_code" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_jurisdiction_code_is_passed_when_set(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_companies_page([], page=1, total_pages=0)])

        _rows(_source("Companies", jurisdiction_code="gb"))

        assert params[0]["jurisdiction_code"] == "gb"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_passes_open_ended_updated_at_range_and_order(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_companies_page([], page=1, total_pages=0)])

        _rows(
            _source(
                "Companies",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 15, 8, 0),
            )
        )

        assert params[0]["updated_at"] == "2026-01-15:"
        assert params[0]["order"] == "updated_at"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_watermark_params_on_first_incremental_sync(self, MockSession) -> None:
        # A first incremental sync has no stored watermark, so no server-side filter should be sent.
        session = MockSession.return_value
        params = _wire(session, [_companies_page([], page=1, total_pages=0)])

        _rows(_source("Companies", should_use_incremental_field=True, db_incremental_field_last_value=None))

        assert "updated_at" not in params[0]
        assert "order" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_officers_never_sends_incremental_filter(self, MockSession) -> None:
        # officers/search has no documented date filter, so it must stay full refresh even if the
        # caller passes a watermark (defensive against a future config wiring bug).
        session = MockSession.return_value
        params = _wire(session, [_officers_page([])])

        _rows(
            _source(
                "Officers",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 15),
            )
        )

        assert "updated_at" not in params[0]
        assert "order" not in params[0]


class TestPageCap:
    def test_maximum_page_cap_stops_pagination(self, caplog: pytest.LogCaptureFixture) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.opencorporates import (
            OpencorporatesPaginator,
        )

        paginator = OpencorporatesPaginator()
        paginator.page = 100

        with caplog.at_level("INFO"):
            paginator.update_state(
                _companies_page([{"company_number": "1", "jurisdiction_code": "gb"}], page=100, total_pages=500),
                data=[{}],
            )

        assert paginator._has_next_page is False
        # Hitting the documented page cap should be surfaced, not fail silently.
        assert any("page cap" in record.message for record in caplog.records)


class TestHttpErrors:
    @parameterized.expand(
        [
            ("unauthorized", 401, "Unauthorized"),
            ("forbidden", 403, "Forbidden"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_permanent_status_raises_without_leaking_token(
        self, _name: str, status: int, reason: str, MockSession
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": {"message": "bad"}}, status=status, reason=reason)])

        with pytest.raises(requests.HTTPError) as exc:
            _rows(_source("Companies"))

        # The api_token rides in the query string, so it must be redacted out of the error message
        # that becomes the user-visible `latest_error`.
        assert str(status) in str(exc.value)
        assert "supersecret" not in str(exc.value)
        assert session.send.call_count == 1


class TestSourceResponse:
    @parameterized.expand(
        [
            ("Companies", ["jurisdiction_code", "company_number"], "created_at"),
            ("Officers", ["id"], None),
        ]
    )
    def test_source_response_keys_and_partitioning(
        self, endpoint: str, expected_keys: list[str], expected_partition: str | None
    ) -> None:
        response = _source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "desc"
        if expected_partition is None:
            assert response.partition_keys is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"

    def test_every_endpoint_builds_a_source_response(self) -> None:
        for endpoint in OPENCORPORATES_ENDPOINTS:
            response = _source(endpoint)
            assert response.name == endpoint
            assert callable(response.items)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("quota_exhausted_token_still_genuine", 403, True),
            ("unauthorized", 401, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status
        session = mock.MagicMock()
        session.get.return_value = response
        with mock.patch(OPENCORPORATES_SESSION_PATCH, return_value=session):
            ok, message = validate_credentials("k")
        assert ok is expected
        if expected:
            assert message is None
        else:
            assert message

    def test_handles_network_error(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(OPENCORPORATES_SESSION_PATCH, return_value=session):
            ok, message = validate_credentials("k")
        assert ok is False
        assert message
