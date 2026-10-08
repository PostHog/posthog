import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.conekta import (
    ConektaCursorPaginator,
    ConektaResumeConfig,
    conekta_source,
    to_epoch_seconds,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.settings import API_VERSION, PAGE_SIZE

SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.conekta.conekta.make_tracked_session"


def _page(rows: list[dict[str, Any]], next_cursor: str | None) -> Response:
    body: dict[str, Any] = {"data": rows, "object": "list", "has_more": next_cursor is not None}
    body["next_page_url"] = (
        f"https://api.conekta.io/orders?limit={PAGE_SIZE}&next={next_cursor}" if next_cursor else None
    )
    body["previous_page_url"] = None
    response = Response()
    response.status_code = 200
    response._content = json.dumps(body).encode()
    return response


def _make_manager(resume_state: ConektaResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    # Snapshot each request at prepare time: the client mutates one Request object across pages.
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return conekta_source("key_priv", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestToEpochSeconds:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1676328434, 1676328434),
            (1676328434.9, 1676328434),
            (datetime(2023, 2, 13, 21, 27, 14, tzinfo=UTC), 1676323634),
            ("1676328434", 1676328434),
            ("2023-02-13T21:27:14+00:00", 1676323634),
            ("nonsense", "nonsense"),
        ],
    )
    def test_coerces_watermark_to_epoch_seconds(self, value, expected):
        assert to_epoch_seconds(value) == expected

    def test_date_maps_to_midnight(self):
        assert to_epoch_seconds(date(2023, 2, 13)) == int(datetime(2023, 2, 13).timestamp())


class TestPaginator:
    def _advance(self, paginator: ConektaCursorPaginator, response: Response, request: Request) -> None:
        paginator.update_state(response)
        paginator.update_request(request)

    def test_keeps_original_params_and_adds_cursor(self):
        paginator = ConektaCursorPaginator()
        request = Request(method="GET", url="https://api.conekta.io/orders", params={"limit": 250, "updated_at.gte": 5})

        self._advance(paginator, _page([{"id": "ord_1"}], "ord_1"), request)

        assert paginator.has_next_page is True
        assert request.params == {"limit": 250, "updated_at.gte": 5, "next": "ord_1"}

    @pytest.mark.parametrize(
        "body",
        [
            {"data": [], "has_more": False, "next_page_url": None},
            {"data": [], "has_more": True, "next_page_url": None},
        ],
    )
    def test_stops_when_no_next_page(self, body):
        response = Response()
        response.status_code = 200
        response._content = json.dumps(body).encode()

        paginator = ConektaCursorPaginator()
        paginator.update_state(response)

        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None

    def test_stops_on_non_json_body(self):
        response = Response()
        response.status_code = 200
        response._content = b"<html>maintenance</html>"

        paginator = ConektaCursorPaginator()
        paginator.update_state(response)

        assert paginator.has_next_page is False


class TestValidateCredentials:
    @mock.patch(SESSION_PATCH)
    def test_probes_orders_with_bearer_token_and_versioned_accept(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("key_priv")

        assert mock_session.call_args.kwargs["headers"]["Accept"] == f"application/vnd.conekta-v{API_VERSION}+json"
        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.conekta.io/orders?limit=1"
        assert call.kwargs["headers"]["Authorization"] == "Bearer key_priv"


class TestRequests:
    @mock.patch(SESSION_PATCH)
    def test_incremental_filter_survives_pagination(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_page([{"id": "ord_1"}], "ord_1"), _page([{"id": "ord_2"}], None)])

        manager = _make_manager()
        rows = _rows(
            _source(
                "orders",
                manager,
                incremental_field="updated_at",
                should_use_incremental_field=True,
                db_incremental_field_last_value=1676328434,
            )
        )

        assert [row["id"] for row in rows] == ["ord_1", "ord_2"]
        # Conekta's next_page_url only echoes limit+next, so the cursor must be re-applied to the
        # original request; otherwise page two drops the filter and walks the whole history.
        assert requests_seen[0]["params"] == {"limit": PAGE_SIZE, "updated_at.gte": 1676328434}
        assert requests_seen[1]["params"] == {"limit": PAGE_SIZE, "updated_at.gte": 1676328434, "next": "ord_1"}
        assert manager.save_state.call_args.args[0] == ConektaResumeConfig(next_cursor="ord_1")

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession):
        session = MockSession.return_value
        requests_seen = _wire(session, [_page([{"id": "ord_5"}], None)])

        rows = _rows(_source("orders", _make_manager(ConektaResumeConfig(next_cursor="ord_4"))))

        assert [row["id"] for row in rows] == ["ord_5"]
        assert requests_seen[0]["params"] == {"limit": PAGE_SIZE, "next": "ord_4"}
