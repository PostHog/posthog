import json
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.polymarket import (
    PolymarketResumeConfig,
    polymarket_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.settings import POLYMARKET_ENDPOINTS

CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
POLYMARKET_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.polymarket.make_tracked_session"
)


def _keyset_response(data_key: str, items: list[dict[str, Any]], *, next_cursor: str | None = None) -> Response:
    body: dict[str, Any] = {data_key: items}
    if next_cursor is not None:
        body["next_cursor"] = next_cursor
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _array_response(items: list[dict[str, Any]]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(items).encode()
    return resp


def _make_manager(resume_state: PolymarketResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock) -> Any:
    return polymarket_source(endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestPolymarketTransport:
    @parameterized.expand(["events", "markets", "series", "tags"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_every_endpoint_pins_an_explicit_order(self, endpoint: str, MockSession) -> None:
        # Without order=id&ascending=true Gamma returns rows in an unspecified order, so a row
        # inserted mid-sync shifts later pages and silently skips or duplicates rows.
        config = POLYMARKET_ENDPOINTS[endpoint]
        session = MockSession.return_value
        response = _keyset_response(config.data_key or "", []) if config.pagination == "keyset" else _array_response([])
        params = _wire(session, [response])

        _rows(_source(endpoint, _make_manager()))

        assert params[0]["order"] == "id"
        assert params[0]["ascending"] == "true"
        assert params[0]["limit"] == config.page_size

    @parameterized.expand(["events", "markets"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_keyset_pagination_walks_then_stops(self, endpoint: str, MockSession) -> None:
        data_key = POLYMARKET_ENDPOINTS[endpoint].data_key or ""
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _keyset_response(data_key, [{"id": "1"}], next_cursor="c1"),
                _keyset_response(data_key, [{"id": "2"}], next_cursor="c2"),
                # next_cursor is absent on the final page.
                _keyset_response(data_key, [{"id": "3"}]),
            ],
        )

        rows = _rows(_source(endpoint, _make_manager()))

        assert [row["id"] for row in rows] == ["1", "2", "3"]
        assert "after_cursor" not in params[0]
        assert [p["after_cursor"] for p in params[1:]] == ["c1", "c2"]

    @parameterized.expand(["series", "tags"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_offset_pagination_advances_and_stops_on_empty_page(self, endpoint: str, MockSession) -> None:
        # These endpoints return a bare JSON array with no wrapper and no cursor, so an empty page
        # is the only signal that the walk is done.
        page_size = POLYMARKET_ENDPOINTS[endpoint].page_size
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _array_response([{"id": str(i)} for i in range(page_size)]),
                _array_response([]),
            ],
        )

        rows = _rows(_source(endpoint, _make_manager()))

        assert len(rows) == page_size
        assert params[0]["offset"] == 0
        assert params[1]["offset"] == page_size

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_keyset_resume_seeds_the_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_keyset_response("events", [{"id": "9"}])])

        _rows(_source("events", _make_manager(PolymarketResumeConfig(cursor="saved"))))

        assert params[0]["after_cursor"] == "saved"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_offset_resume_seeds_the_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_array_response([])])

        _rows(_source("tags", _make_manager(PolymarketResumeConfig(offset=1000))))

        assert params[0]["offset"] == 1000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_a_cursor_resume_state_is_ignored_by_an_offset_endpoint(self, MockSession) -> None:
        # The two styles share one resume dataclass. Seeding an offset paginator with a cursor (or
        # the reverse) would either crash or restart the walk at the wrong place.
        session = MockSession.return_value
        params = _wire(session, [_array_response([])])

        _rows(_source("tags", _make_manager(PolymarketResumeConfig(cursor="not-an-offset"))))

        assert params[0]["offset"] == 0

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_keyset_checkpoint_saves_the_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _keyset_response("events", [{"id": "1"}], next_cursor="c1"),
                _keyset_response("events", [{"id": "2"}]),
            ],
        )
        manager = _make_manager()

        _rows(_source("events", manager))

        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert [s.cursor for s in saved] == ["c1"]
        assert all(s.offset is None for s in saved)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_offset_checkpoint_saves_the_offset(self, MockSession) -> None:
        page_size = POLYMARKET_ENDPOINTS["tags"].page_size
        session = MockSession.return_value
        _wire(
            session,
            [
                _array_response([{"id": str(i)} for i in range(page_size)]),
                _array_response([]),
            ],
        )
        manager = _make_manager()

        _rows(_source("tags", manager))

        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert [s.offset for s in saved] == [page_size]
        assert all(s.cursor is None for s in saved)

    @parameterized.expand([("events", ["id"]), ("markets", ["id"]), ("series", ["id"]), ("tags", ["id"])])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partitions_on_created_at(self, endpoint: str, expected_keys: list[str], MockSession) -> None:
        # createdAt is stable; partitioning on updatedAt would rewrite partitions every sync.
        config = POLYMARKET_ENDPOINTS[endpoint]
        session = MockSession.return_value
        response = _keyset_response(config.data_key or "", []) if config.pagination == "keyset" else _array_response([])
        _wire(session, [response])

        result = _source(endpoint, _make_manager())

        assert result.primary_keys == expected_keys
        assert result.partition_keys == ["createdAt"]

    @parameterized.expand([("ok", 200, True), ("forbidden", 403, False), ("server_error", 500, False)])
    @mock.patch(POLYMARKET_SESSION_PATCH)
    def test_validate_credentials_maps_status(self, _name: str, status: int, expected: bool, MockSession) -> None:
        resp = Response()
        resp.status_code = status
        MockSession.return_value.get.return_value = resp

        assert validate_credentials() is expected

    @mock.patch(POLYMARKET_SESSION_PATCH)
    def test_validate_credentials_survives_transport_error(self, MockSession) -> None:
        MockSession.side_effect = OSError("boom")

        assert validate_credentials() is False
