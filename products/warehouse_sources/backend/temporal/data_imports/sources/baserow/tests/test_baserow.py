import threading
from collections.abc import Iterable
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.baserow.baserow import (
    BaserowPaginator,
    BaserowResumeConfig,
    _BoundedSession,
    _read_capped,
    check_table_read_permission,
    list_tables,
    normalize_base_url,
    resolve_table_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.baserow.settings import (
    CONNECT_TIMEOUT_SECONDS,
    DEFAULT_BASE_URL,
    READ_TIMEOUT_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.baserow.source import BaserowSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.baserow import (
    BaserowSourceConfig,
)

BASE_URL = "https://api.baserow.io"


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, DEFAULT_BASE_URL),
            ("", DEFAULT_BASE_URL),
            ("   ", DEFAULT_BASE_URL),
            ("baserow.example.com", "https://baserow.example.com"),
            ("https://baserow.example.com/", "https://baserow.example.com"),
            ("https://baserow.example.com:8443", "https://baserow.example.com:8443"),
        ],
    )
    def test_normalizes_valid_urls(self, raw: str | None, expected: str) -> None:
        assert normalize_base_url(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "http://baserow.example.com",  # plaintext would put the token on the wire in the clear
            "https://user:pass@baserow.example.com",  # credentials in the authority
            "https://evil.com\\@baserow.example.com",  # urlparse/http-client host disagreement
            "https://evil.com%40baserow.example.com",  # encoded authority delimiter
            "https://",
        ],
    )
    def test_rejects_unsafe_urls(self, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_base_url(raw)


class TestBaserowPaginator:
    def _response(self, body: dict[str, Any]) -> MagicMock:
        response = MagicMock()
        response.json.return_value = body
        return response

    def test_follows_same_origin_next_url(self) -> None:
        paginator = BaserowPaginator(BASE_URL)
        paginator.update_state(
            self._response({"count": 300, "next": f"{BASE_URL}/api/database/rows/table/1/?page=2", "results": []})
        )

        assert paginator.has_next_page is True
        request = Request(method="GET", url=f"{BASE_URL}/api/database/rows/table/1/", params={"size": 200})
        paginator.update_request(request)
        assert request.url == f"{BASE_URL}/api/database/rows/table/1/?page=2"

    def test_stops_when_next_is_null(self) -> None:
        paginator = BaserowPaginator(BASE_URL)
        paginator.update_state(self._response({"count": 1, "next": None, "results": [{"id": 1}]}))

        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None

    @pytest.mark.parametrize(
        "next_url",
        [
            "http://api.baserow.io/api/database/rows/table/1/?page=2",  # https downgrade
            "https://evil.example.com/api/database/rows/table/1/?page=2",  # other host
            "https://api.baserow.io:8443/api/database/rows/table/1/?page=2",  # other port
        ],
    )
    def test_rejects_next_url_off_the_configured_origin(self, next_url: str) -> None:
        paginator = BaserowPaginator(BASE_URL)
        with pytest.raises(ValueError):
            paginator.update_state(self._response({"count": 300, "next": next_url, "results": []}))

    def test_resume_state_round_trip(self) -> None:
        next_url = f"{BASE_URL}/api/database/rows/table/1/?page=3"
        paginator = BaserowPaginator(BASE_URL)
        paginator.update_state(self._response({"count": 500, "next": next_url, "results": []}))
        assert paginator.get_resume_state() == {"next_url": next_url}

        resumed = BaserowPaginator(BASE_URL)
        resumed.set_resume_state({"next_url": next_url})
        request = Request(method="GET", url=f"{BASE_URL}/api/database/rows/table/1/", params={"size": 200})
        resumed.init_request(request)
        assert request.url == next_url

    def test_set_resume_state_rejects_cross_origin_url(self) -> None:
        paginator = BaserowPaginator(BASE_URL)
        with pytest.raises(ValueError):
            paginator.set_resume_state({"next_url": "https://evil.example.com/api/database/rows/table/1/?page=2"})

    def test_rejects_repeated_next_url(self) -> None:
        # A host that keeps echoing the same next link would otherwise loop until the
        # activity timeout; the second identical link aborts the sync.
        next_url = f"{BASE_URL}/api/database/rows/table/1/?page=2"
        paginator = BaserowPaginator(BASE_URL)
        paginator.update_state(self._response({"count": 300, "next": next_url, "results": []}))
        with pytest.raises(ValueError, match="not advancing"):
            paginator.update_state(self._response({"count": 300, "next": next_url, "results": []}))

    def test_aborts_when_page_budget_exhausted(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.baserow.baserow.MAX_PAGES_PER_SYNC",
            2,
        ):
            paginator = BaserowPaginator(BASE_URL)
            paginator.update_state(self._response({"count": 9, "next": f"{BASE_URL}/rows/?page=2", "results": []}))
            paginator.update_state(self._response({"count": 9, "next": f"{BASE_URL}/rows/?page=3", "results": []}))
            with pytest.raises(ValueError, match="page limit"):
                paginator.update_state(self._response({"count": 9, "next": f"{BASE_URL}/rows/?page=4", "results": []}))


class TestResolveTableId:
    def test_schema_metadata_short_circuits_without_listing_tables(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.baserow.baserow.list_tables"
        ) as mock_list:
            table_id = resolve_table_id(None, "tok", "Projects", {"table_id": 42, "database_id": 1})

        assert table_id == 42
        mock_list.assert_not_called()

    def test_falls_back_to_name_lookup(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.baserow.baserow.list_tables",
            return_value=[{"id": 7, "name": "Projects", "order": 1, "database_id": 1}],
        ):
            assert resolve_table_id(None, "tok", "Projects", None) == 7

    def test_raises_for_unknown_schema(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.baserow.baserow.list_tables",
            return_value=[{"id": 7, "name": "Projects", "order": 1, "database_id": 1}],
        ):
            with pytest.raises(ValueError, match="renamed or deleted"):
                resolve_table_id(None, "tok", "Deleted table", None)


class TestCheckTableReadPermission:
    @pytest.mark.parametrize(
        ("status_code", "expects_reason"),
        [
            (200, False),
            (401, True),  # ERROR_NO_PERMISSION_TO_TABLE — read toggle off for this table
            (403, True),
            (429, False),  # a throttle is not a missing permission
            (500, False),
        ],
    )
    def test_maps_status_to_reason(self, status_code: int, expects_reason: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            reason = check_table_read_permission(None, "tok", 42)

        assert (reason is not None) is expects_reason
        assert network.requests_log[0].path == "/api/database/rows/table/42/"
        assert network.requests_log[0].param("size") == "1"


class TestListTables:
    @pytest.mark.parametrize(
        ("status_code", "body"),
        [
            (302, b""),  # a redirect the no-redirect session leaves unfollowed: empty body
            (200, b"<html>not the API</html>"),  # wrong URL / proxy returns an HTML page
        ],
    )
    def test_non_json_response_raises_clear_error(self, status_code: int, body: bytes) -> None:
        with scripted_network([ScriptedResponse(status=status_code, body=body)]) as network:
            with pytest.raises(ValueError, match="unexpected response"):
                list_tables(None, "tok")
        assert [request.path for request in network.requests_log] == ["/api/database/tables/all-tables/"]


def _streamed_response(chunks: list[bytes], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    raw = MagicMock()
    raw.stream.return_value = iter(chunks)
    resp.raw = raw
    return resp


class TestBoundedSession:
    def test_read_capped_returns_full_body_under_limit(self) -> None:
        assert _read_capped(_streamed_response([b"ab", b"cd"])) == b"abcd"

    def test_read_capped_aborts_over_limit(self) -> None:
        # A hostile host can return an arbitrarily large / highly compressed body; the cap
        # aborts mid-stream instead of buffering it all into worker memory.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.baserow.baserow.MAX_RESPONSE_BYTES",
            3,
        ):
            with pytest.raises(ValueError, match="exceeded"):
                _read_capped(_streamed_response([b"ab", b"cd"]))

    def test_read_capped_aborts_on_slow_drip(self) -> None:
        # READ_TIMEOUT_SECONDS is only socket-inactivity, so a host that trickles bytes stays
        # under it forever; the wall-clock deadline abandons the stalled read and closes the
        # response to unblock the socket.
        stalled = threading.Event()

        def stalled_stream(*_a: Any, **_k: Any) -> Iterable[bytes]:
            stalled.wait()  # never delivers until the test releases it
            yield b"x"

        response = MagicMock()
        response.raw.stream.side_effect = stalled_stream
        try:
            with patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.baserow.baserow.READ_DEADLINE_SECONDS",
                0.1,
            ):
                with pytest.raises(ValueError, match="not fully delivered"):
                    _read_capped(response)
            response.close.assert_called_once()
        finally:
            stalled.set()

    def test_send_defaults_timeout_and_streams_on_row_sync_path(self) -> None:
        # RESTClient.send() passes no timeout — the session must supply one so a stalled
        # host can't hang the request thread, and stream so the body stays capped.
        prepared = Request(method="GET", url=f"{BASE_URL}/x").prepare()
        with patch.object(requests.Session, "send", return_value=_streamed_response([b"{}"])) as parent_send:
            _BoundedSession().send(prepared)
        forwarded = parent_send.call_args.kwargs
        assert forwarded["allow_redirects"] is False
        assert forwarded["stream"] is True
        assert forwarded["timeout"] == (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)

    def test_send_respects_explicit_timeout(self) -> None:
        prepared = Request(method="GET", url=f"{BASE_URL}/x").prepare()
        with patch.object(requests.Session, "send", return_value=_streamed_response([b"{}"])) as parent_send:
            _BoundedSession().send(prepared, timeout=5)
        assert parent_send.call_args.kwargs["timeout"] == 5


class TestBaserowRowsSourceResumeBehavior:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(BaserowSource(), BaserowSourceConfig(database_token="test-token", base_url=None))

    @staticmethod
    def _tables() -> ScriptedResponse:
        return ScriptedResponse(json=[{"id": 42, "name": "Projects", "database_id": 1}])

    @staticmethod
    def _page(rows: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
        return ScriptedResponse(json={"count": len(rows), "next": next_url, "previous": None, "results": rows})

    def test_fresh_run_pages_through_next_urls_and_checkpoints(self) -> None:
        page_2 = f"{BASE_URL}/api/database/rows/table/42/?page=2&size=200&user_field_names=true"
        result = self._driver().run(
            "Projects", [self._tables(), self._page([{"id": 1}, {"id": 2}], page_2), self._page([{"id": 3}])]
        )

        # The resource yields one batch (list of row dicts) per page.
        assert [[row["id"] for row in page] for page in result.items] == [[1, 2], [3]]
        # First request hits the table path with the declared params; the second follows the
        # self-contained next URL with the original params dropped.
        assert result.requests[1].path == "/api/database/rows/table/42/"
        assert result.requests[1].query == {"size": ("200",), "user_field_names": ("true",)}
        assert result.requests[2].url == page_2
        assert result.saved_states == [BaserowResumeConfig(next_url=page_2)]
        assert result.committed_states == [BaserowResumeConfig(next_url=page_2)]
        assert result.raised is None

    def test_resume_starts_from_saved_next_url(self) -> None:
        saved_url = f"{BASE_URL}/api/database/rows/table/42/?page=5&size=200&user_field_names=true"
        result = self._driver().run(
            "Projects",
            [self._tables(), self._page([{"id": 801}])],
            resume_state=BaserowResumeConfig(next_url=saved_url),
        )

        assert result.requests[1].url == saved_url
        assert result.rows == [{"id": 801}]
        assert result.raised is None

    def test_terminal_single_page_does_not_save_state(self) -> None:
        result = self._driver().run("Projects", [self._tables(), self._page([{"id": 1}])])

        assert result.saved_states == []
        assert result.raised is None

    def test_cross_origin_next_url_aborts_the_sync(self) -> None:
        # Guards the wiring: the rows resource must run the origin-pinned paginator, so a
        # tampered body can't bounce the token-bearing request to another host.
        result = self._driver().run(
            "Projects", [self._tables(), self._page([{"id": 1}], "https://evil.example.com/rows/?page=2")]
        )

        assert isinstance(result.raised, ValueError)
        assert "not on the configured instance" in str(result.raised)
        assert result.paths == ["/api/database/tables/all-tables/", "/api/database/rows/table/42/"]
