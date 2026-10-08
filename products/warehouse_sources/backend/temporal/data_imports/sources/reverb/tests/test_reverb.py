import json
from datetime import UTC, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.reverb import (
    ReverbResumeConfig,
    _format_datetime,
    _inject_payout_id,
    reverb_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.settings import PER_PAGE

CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
REVERB_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.reverb.reverb.make_tracked_session"
)


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("string_passthrough", "not-a-date", "not-a-date"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestInjectPayoutId:
    @parameterized.expand(
        [
            (
                "well_formed_href",
                {"_links": {"line_items": {"href": "https://api.reverb.com/api/my/payouts/54/line_items"}}},
                54,
            ),
            ("missing_links", {}, None),
            ("missing_line_items", {"_links": {}}, None),
            ("malformed_href", {"_links": {"line_items": {"href": "not-a-url"}}}, None),
        ]
    )
    def test_id_extraction(self, _name: str, row: dict[str, Any], expected_id: int | None) -> None:
        result = _inject_payout_id(dict(row))
        assert result.get("id") == expected_id


def _response(
    response_key: str,
    items: list[dict[str, Any]] | None,
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
    drop_key: bool = False,
) -> Response:
    body: dict[str, Any] = {}
    if not drop_key:
        body[response_key] = items or []
    if current_page is not None:
        body["current_page"] = current_page
    if total_pages is not None:
        body["total_pages"] = total_pages
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ReverbResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    kwargs.setdefault("should_use_incremental_field", False)
    kwargs.setdefault("db_incremental_field_last_value", None)
    kwargs.setdefault("api_version", "3.0")
    return reverb_source(
        api_token="token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestReverbSourceOrders:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("orders", [{"order_number": "2"}], current_page=2, total_pages=2)])

        rows = _rows(_source("Orders", _make_manager(ReverbResumeConfig(next_page=2))))

        assert [r["order_number"] for r in rows] == ["2"]
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_metadata_full_page_continues(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"order_number": str(i)} for i in range(PER_PAGE)]
        _wire(session, [_response("orders", full_page), _response("orders", [{"order_number": "last"}])])

        rows = _rows(_source("Orders", _make_manager()))

        assert len(rows) == PER_PAGE + 1
        assert session.send.call_count == 2


class TestReverbSourcePayouts:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_window_uses_created_date_params(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("payouts", [], total_pages=1)])

        _rows(
            _source(
                "Payouts",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["created_start_date"] == "2026-03-04T00:00:00Z"
        assert "created_end_date" in snapshots[0]["params"]


class TestValidateCredentials:
    @mock.patch(REVERB_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("token", "3.0") == (True, 200)
