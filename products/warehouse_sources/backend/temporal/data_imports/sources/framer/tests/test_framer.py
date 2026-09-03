import os
import json
import math
import socket
import threading
from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Optional, cast

import pytest

from parameterized import parameterized
from websockets.exceptions import InvalidMessage

from products.warehouse_sources.backend.temporal.data_imports.sources.framer import devalue
from products.warehouse_sources.backend.temporal.data_imports.sources.framer.framer import (
    FramerAPIError,
    FramerClient,
    framer_source,
    parse_project_id,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.framer.settings import (
    DEPLOYMENTS_PAGE_SIZE,
    ENDPOINTS,
    PRIMARY_KEYS,
)

PROJECT_ID = "a" * 20


class FakeFramerServer:
    """Scripted in-memory stand-in for the Framer headless WebSocket channel."""

    def __init__(
        self,
        methods: Optional[dict[str, Any]] = None,
        graceful_disconnect: bool = False,
        ready_message: Optional[dict[str, Any]] = None,
    ) -> None:
        self.methods = methods or {}
        self.sent: list[Any] = []
        self.closed = False
        self.auto_respond = True
        self.incoming: deque[str] = deque()
        ready = ready_message if ready_message is not None else {"type": "ready", "requestId": "req-1"}
        if graceful_disconnect:
            ready = {**ready, "gracefulDisconnect": True}
        self.incoming.append(devalue.stringify(ready))

    def __call__(self, url: str, **kwargs: Any) -> "FakeFramerServer":
        self.url = url
        self.connect_kwargs = kwargs
        return self

    def enqueue_raw(self, text: str) -> None:
        self.incoming.append(text)

    def send(self, text: str) -> None:
        message = devalue.parse(text)
        self.sent.append(message)
        if not self.auto_respond:
            return
        if message.get("type") == "pluginReadySignal":
            self.incoming.append(devalue.stringify({"type": "pluginReadyResponse", "mode": "api"}))
        elif message.get("type") == "methodInvocation":
            handler = self.methods[message["methodName"]]
            result = handler(*message.get("args") or []) if callable(handler) else handler
            self.incoming.append(devalue.stringify({"type": "methodResponse", "id": message["id"], "result": result}))

    def recv(self, timeout: Optional[float] = None) -> str:
        if not self.incoming:
            raise TimeoutError()
        return self.incoming.popleft()

    def close(self) -> None:
        self.closed = True


class FakeConnectProxy:
    """In-memory CONNECT proxy with a configurable status line, so tests can speak the
    `HTTP/1.0 200 OK` that goproxy-based egress proxies (Smokescreen) answer with."""

    def __init__(self, status_line: str) -> None:
        self.status_line = status_line
        self.connect_request = ""
        self.tunneled = b""
        self._server = socket.socket()
        self._server.settimeout(10)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        connection, _ = self._server.accept()
        connection.settimeout(10)
        try:
            request = b""
            while b"\r\n\r\n" not in request:
                request += connection.recv(4096)
            self.connect_request = request.decode()
            connection.sendall(f"{self.status_line}\r\n\r\n".encode())
            while data := connection.recv(4096):
                self.tunneled += data
        except OSError:
            pass
        finally:
            connection.close()

    def join(self) -> None:
        self._thread.join(timeout=10)
        self._server.close()


@pytest.fixture(autouse=True)
def no_ambient_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    # The client resolves proxies from process env, so an ambient HTTP(S)_PROXY on the
    # host would reroute every connect in this file through a real proxy.
    for name in [key for key in os.environ if key.lower().endswith("_proxy")]:
        monkeypatch.delenv(name)


def make_client(server: FakeFramerServer) -> FramerClient:
    client = FramerClient(PROJECT_ID, "test-key", protocol_version="0.1.29", connect_fn=server)
    client.connect()
    return client


class TestFramer:
    # (payload stringified by the reference devalue JS library, expected parsed value)
    @parameterized.expand(
        [
            ('[{"type":1},"ping"]', {"type": "ping"}),
            (
                '[{"type":1,"methodName":2,"id":3,"args":4},"methodInvocation","getCollectionItems2",3,[5],"abc"]',
                {"type": "methodInvocation", "methodName": "getCollectionItems2", "id": 3, "args": ["abc"]},
            ),
            (
                '[{"type":1,"id":2,"result":3},"methodResponse",0,[4],{"id":5,"name":6,"readonly":7,"managedBy":8,"n":9},"a","Blog",false,"user",3.5]',
                {
                    "type": "methodResponse",
                    "id": 0,
                    "result": [{"id": "a", "name": "Blog", "readonly": False, "managedBy": "user", "n": 3.5}],
                },
            ),
            (
                '[{"type":1,"id":2,"result":3},"methodResponse",1,{"deployments":4,"hasNextPage":9},[5],{"id":6,"createdAt":7,"deployedBy":8},"d1","2026-01-02T03:04:05.000Z",null,false]',
                {
                    "type": "methodResponse",
                    "id": 1,
                    "result": {
                        "deployments": [{"id": "d1", "createdAt": "2026-01-02T03:04:05.000Z", "deployedBy": None}],
                        "hasNextPage": False,
                    },
                },
            ),
            # Repeated references: devalue dedupes identical objects and strings by index.
            (
                '[{"a":1,"b":1,"c":3},{"id":2,"name":3},"f1","title"]',
                {"a": {"id": "f1", "name": "title"}, "b": {"id": "f1", "name": "title"}, "c": "title"},
            ),
            ("-1", None),
        ]
    )
    def test_parse_reference_fixtures(self, encoded: str, expected: Any) -> None:
        assert devalue.parse(encoded) == expected

    def test_parse_typed_values(self) -> None:
        # Reference fixture covering Date, undefined, null, BigInt, Set, and Map wrappers.
        encoded = (
            '[{"type":1,"id":2,"result":3},"methodResponse",2,'
            '{"when":4,"missing":-1,"empty":5,"big":6,"s":7,"m":10},'
            '["Date","2026-01-02T03:04:05.678Z"],null,["BigInt","123"],["Set",8,9],1,"x",["Map",11,12],"k","v"]'
        )
        result = devalue.parse(encoded)["result"]
        assert result["when"] == datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
        assert result["missing"] is None
        assert result["empty"] is None
        assert result["big"] == 123
        assert result["s"] == [1, "x"]
        assert result["m"] == {"k": "v"}

    def test_parse_unknown_custom_wrapper_falls_back_to_payload(self) -> None:
        assert devalue.parse('[{"node":1},["plugin-marshal",2],{"id":3},"n1"]') == {"node": {"id": "n1"}}

    def test_parse_special_numbers(self) -> None:
        parsed = devalue.parse('[{"nan":-3,"inf":-4,"ninf":-5,"nzero":-6}]')
        assert math.isnan(parsed["nan"])
        assert parsed["inf"] == math.inf
        assert parsed["ninf"] == -math.inf
        assert parsed["nzero"] == 0.0

    @parameterized.expand(
        [
            ({"type": "ping"},),
            ({"type": "methodInvocation", "methodName": "getCollections", "id": 0, "args": []},),
            ({"type": "methodInvocation", "methodName": "listDeployments", "id": 7, "args": [30, "cursor-1"]},),
            ({"nested": {"list": [1, "two", False, None], "n": -1}},),
        ]
    )
    def test_stringify_round_trips(self, value: Any) -> None:
        assert devalue.parse(devalue.stringify(value)) == value

    def test_stringify_matches_reference_encoding(self) -> None:
        # Byte-for-byte fixture from the reference JS library.
        assert devalue.stringify({"type": "ping"}) == '[{"type":1},"ping"]'

    @parameterized.expand(
        [
            (PROJECT_ID,),
            (f"https://framer.com/projects/My-Site--{PROJECT_ID}",),
            (f"https://framer.com/projects/My-Site--{PROJECT_ID}?node=abc",),
            (f"https://www.framer.com/PROJECTS/{PROJECT_ID}",),
            (f"projects/My%20Site--{PROJECT_ID}",),
        ]
    )
    def test_parse_project_id_valid_inputs(self, value: str) -> None:
        assert parse_project_id(value) == PROJECT_ID

    @parameterized.expand(
        [
            ("",),
            ("not-a-project",),
            ("https://framer.com/projects/",),
            ("https://framer.com/projects/My-Site--tooshort",),
            (f"https://framer.com/other/{PROJECT_ID}",),
        ]
    )
    def test_parse_project_id_rejects_invalid(self, value: str) -> None:
        assert parse_project_id(value) is None

    def test_client_handshake_and_call(self) -> None:
        server = FakeFramerServer(methods={"getProjectInfo2": {"id": PROJECT_ID, "name": "Site"}})
        client = make_client(server)
        assert client.call("getProjectInfo2") == {"id": PROJECT_ID, "name": "Site"}
        assert server.sent[0] == {"type": "pluginReadySignal"}
        assert "Authorization" in server.connect_kwargs["additional_headers"]
        assert f"projectId={PROJECT_ID}" in server.url
        assert "sdkVersion=0.1.29" in server.url

    def test_client_close_sends_graceful_disconnect(self) -> None:
        server = FakeFramerServer(graceful_disconnect=True)
        client = make_client(server)
        client.close()
        assert server.sent[-1] == {"type": "client-disconnect"}
        assert server.closed

    def test_client_close_without_graceful_disconnect(self) -> None:
        server = FakeFramerServer()
        client = make_client(server)
        client.close()
        assert all(message.get("type") != "client-disconnect" for message in server.sent)
        assert server.closed

    def test_client_raises_on_server_error_message(self) -> None:
        server = FakeFramerServer(
            ready_message={"type": "error", "code": "UNAUTHORIZED", "message": "API key does not have access"}
        )
        client = FramerClient(PROJECT_ID, "bad-key", protocol_version="0.1.29", connect_fn=server)
        with pytest.raises(FramerAPIError) as exc_info:
            client.connect()
        assert exc_info.value.code == "UNAUTHORIZED"
        assert not exc_info.value.retryable
        assert "Framer API error UNAUTHORIZED" in str(exc_info.value)

    @parameterized.expand(
        [
            ("POOL_EXHAUSTED",),
            ("TOKEN_SESSION_LIMIT",),
        ]
    )
    def test_client_marks_transient_server_errors_retryable(self, code: str) -> None:
        server = FakeFramerServer(ready_message={"type": "error", "code": code, "message": "busy"})
        client = FramerClient(PROJECT_ID, "key", protocol_version="0.1.29", connect_fn=server)
        with pytest.raises(FramerAPIError) as exc_info:
            client.connect()
        assert exc_info.value.retryable

    def test_client_wraps_handshake_eof_as_retryable(self) -> None:
        def connect_fn(*args: Any, **kwargs: Any) -> Any:
            raise InvalidMessage("did not receive a valid HTTP response")

        client = FramerClient(PROJECT_ID, "test-key", protocol_version="0.1.29", connect_fn=connect_fn)
        with pytest.raises(FramerAPIError) as exc_info:
            client.connect()
        assert exc_info.value.code == "CONNECTION_CLOSED"
        assert exc_info.value.retryable

    def test_client_raises_on_method_error(self) -> None:
        server = FakeFramerServer()
        client = make_client(server)
        server.enqueue_raw(devalue.stringify({"type": "methodResponse", "id": 0, "error": "Node not found"}))
        # Disable the auto-responder so the queued error response is the one consumed.
        server.auto_respond = False
        with pytest.raises(FramerAPIError) as exc_info:
            client.call("getNode")
        assert "Node not found" in str(exc_info.value)

    def test_client_ignores_unrelated_messages(self) -> None:
        server = FakeFramerServer(methods={"getLocales": [{"id": "l1"}]})
        client = make_client(server)
        server.incoming.appendleft(devalue.stringify({"type": "permissionUpdate", "permissionMap": {}}))
        assert client.call("getLocales") == [{"id": "l1"}]

    def test_client_reassembles_chunked_messages(self) -> None:
        server = FakeFramerServer()
        client = make_client(server)
        full = devalue.stringify({"type": "methodResponse", "id": 0, "result": [{"id": "big"}]})
        middle = len(full) // 2
        server.auto_respond = False
        server.enqueue_raw(json.dumps({"$chunk": 1, "id": "c1", "seq": 0, "data": full[:middle]}))
        server.enqueue_raw(json.dumps({"$chunk": 1, "id": "c1", "seq": -1, "data": full[middle:]}))
        assert client.call("getCollections") == [{"id": "big"}]

    @parameterized.expand(
        [
            ("HTTP/1.0 200 OK",),  # goproxy/Smokescreen success line, rejected by websockets < 17
            ("HTTP/1.1 200 Connection established",),
        ]
    )
    def test_client_tunnels_through_env_configured_proxy(self, status_line: str) -> None:
        proxy = FakeConnectProxy(status_line)
        server = FakeFramerServer()
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setenv("HTTPS_PROXY", f"http://pod:x@127.0.0.1:{proxy.port}")
            client = FramerClient(PROJECT_ID, "test-key", protocol_version="0.1.29", connect_fn=server)
            client.connect()
        client.close()
        assert proxy.connect_request.startswith("CONNECT api.framer.com:443 ")
        assert "Proxy-Authorization: Basic" in proxy.connect_request
        sock = server.connect_kwargs["sock"]
        sock.sendall(b"tunneled")
        sock.close()
        proxy.join()
        assert proxy.tunneled == b"tunneled"

    def test_client_wraps_proxy_denial_as_retryable(self) -> None:
        proxy = FakeConnectProxy("HTTP/1.0 407 Request rejected by proxy")
        server = FakeFramerServer()
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setenv("HTTPS_PROXY", f"http://127.0.0.1:{proxy.port}")
            client = FramerClient(PROJECT_ID, "test-key", protocol_version="0.1.29", connect_fn=server)
            with pytest.raises(FramerAPIError) as exc_info:
                client.connect()
        proxy.join()
        assert exc_info.value.code == "PROXY"
        assert exc_info.value.retryable

    def test_client_connects_directly_without_proxy(self) -> None:
        server = FakeFramerServer()
        make_client(server)
        assert "sock" not in server.connect_kwargs

    def test_validate_credentials_success(self) -> None:
        server = FakeFramerServer(methods={"getProjectInfo2": {"id": PROJECT_ID, "name": "Site"}})
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(
                "products.warehouse_sources.backend.temporal.data_imports.sources.framer.framer.websocket_connect",
                server,
            )
            valid, error = validate_credentials(PROJECT_ID, "key", "0.1.29")
        assert valid is True
        assert error is None

    def test_validate_credentials_unauthorized(self) -> None:
        server = FakeFramerServer(ready_message={"type": "error", "code": "UNAUTHORIZED", "message": "no access"})
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(
                "products.warehouse_sources.backend.temporal.data_imports.sources.framer.framer.websocket_connect",
                server,
            )
            valid, error = validate_credentials(PROJECT_ID, "bad", "0.1.29")
        assert valid is False
        assert error is not None and "API key" in error

    def test_validate_credentials_invalid_project(self) -> None:
        valid, error = validate_credentials("not a project", "key", "0.1.29")
        assert valid is False
        assert error is not None and "project URL or ID" in error

    def test_validate_credentials_transient_error_is_clean(self) -> None:
        # A transient channel condition must surface a clean retry message, not Framer's raw
        # "Framer API error <CODE>" text.
        server = FakeFramerServer(ready_message={"type": "error", "code": "POOL_EXHAUSTED", "message": "busy"})
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(
                "products.warehouse_sources.backend.temporal.data_imports.sources.framer.framer.websocket_connect",
                server,
            )
            valid, error = validate_credentials(PROJECT_ID, "key", "0.1.29")
        assert valid is False
        assert error is not None
        assert "Framer API error" not in error
        assert "try again" in error

    def _run_endpoint(self, endpoint: str, methods: dict[str, Any]) -> list[dict[str, Any]]:
        server = FakeFramerServer(methods=methods)
        response = framer_source(PROJECT_ID, "key", endpoint, protocol_version="0.1.29")
        assert response.name == endpoint
        assert response.primary_keys == PRIMARY_KEYS[endpoint]
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(
                "products.warehouse_sources.backend.temporal.data_imports.sources.framer.framer.websocket_connect",
                server,
            )
            batches = cast(Iterable[list[dict[str, Any]]], response.items())
            rows = [row for batch in batches for row in batch]
        assert server.closed
        return rows

    def test_project_rows(self) -> None:
        rows = self._run_endpoint(
            "Project",
            {
                "getProjectInfo2": {"id": PROJECT_ID, "name": "Site", "apiVersion1Id": "v1id"},
                "getPublishInfo": {
                    "production": {"url": "https://site.framer.website", "deploymentTime": 1},
                    "staging": None,
                },
            },
        )
        assert rows == [
            {
                "id": PROJECT_ID,
                "name": "Site",
                "apiVersion1Id": "v1id",
                "production": {"url": "https://site.framer.website", "deploymentTime": 1},
                "staging": None,
            }
        ]

    def test_pages_rows_strip_class_marker(self) -> None:
        rows = self._run_endpoint(
            "Pages",
            {
                "getCanvasRoot": {"__class": "CanvasRootNode", "id": "root"},
                "getNodesWithType": lambda node_id, node_type: (
                    [{"__class": "WebPageNode", "id": "page-1", "path": "/about", "collectionId": None, "draft": False}]
                    if (node_id, node_type) == ("root", "WebPageNode")
                    else []
                ),
            },
        )
        assert rows == [{"id": "page-1", "path": "/about", "collectionId": None, "draft": False}]

    def test_collections_rows_include_fields(self) -> None:
        rows = self._run_endpoint(
            "Collections",
            {
                "getCollections": [{"id": "c1", "name": "Blog", "readonly": False, "managedBy": "user"}],
                "getCollectionFields2": [{"id": "f1", "name": "Title", "type": "string"}],
            },
        )
        assert rows == [
            {
                "id": "c1",
                "name": "Blog",
                "readonly": False,
                "managedBy": "user",
                "fields": [{"id": "f1", "name": "Title", "type": "string"}],
            }
        ]

    def test_collection_items_rows(self) -> None:
        rows = self._run_endpoint(
            "CollectionItems",
            {
                "getCollections": [{"id": "c1", "name": "Blog"}],
                "getCollectionFields2": [
                    {"id": "f1", "name": "Title", "type": "string"},
                    {"id": "f2", "name": "Title", "type": "string"},
                ],
                "getCollectionItems2": [
                    {
                        "nodeId": "n1",
                        "externalId": None,
                        "slug": "hello",
                        "slugByLocale": {"default": "hello"},
                        "draft": False,
                        "createdAt": "2026-01-01T00:00:00.000Z",
                        "updatedAt": "2026-01-02T00:00:00.000Z",
                        "fieldData": {
                            "f1": {"type": "string", "value": "Hello"},
                            "f2": {"type": "string", "value": "Duplicate name"},
                            "f3": {"type": "image", "value": {"url": "https://example.com/a.png"}},
                        },
                    }
                ],
            },
        )
        assert rows == [
            {
                "id": "n1",
                "nodeId": "n1",
                "collectionId": "c1",
                "collectionName": "Blog",
                "slug": "hello",
                "slugByLocale": {"default": "hello"},
                "draft": False,
                "createdAt": "2026-01-01T00:00:00.000Z",
                "updatedAt": "2026-01-02T00:00:00.000Z",
                "fieldData": {
                    "Title": "Hello",
                    # Second field with the same display name keeps its unique field id.
                    "f2": "Duplicate name",
                    "f3": {"url": "https://example.com/a.png"},
                },
            }
        ]

    def test_collection_items_prefers_external_id(self) -> None:
        rows = self._run_endpoint(
            "CollectionItems",
            {
                "getCollections": [{"id": "c1", "name": "Blog"}],
                "getCollectionFields2": [],
                "getCollectionItems2": [{"nodeId": "n1", "externalId": "ext-1", "slug": "s", "fieldData": {}}],
            },
        )
        assert rows[0]["id"] == "ext-1"
        assert rows[0]["nodeId"] == "n1"

    def test_collection_items_keep_field_whose_name_matches_another_field_id(self) -> None:
        rows = self._run_endpoint(
            "CollectionItems",
            {
                "getCollections": [{"id": "c1", "name": "Blog"}],
                # "f1" displays as "f2", which is also the raw id of the second (unnamed) field.
                "getCollectionFields2": [{"id": "f1", "name": "f2", "type": "string"}],
                "getCollectionItems2": [
                    {
                        "nodeId": "n1",
                        "fieldData": {
                            "f1": {"type": "string", "value": "named"},
                            "f2": {"type": "string", "value": "unnamed"},
                        },
                    }
                ],
            },
        )
        assert rows[0]["fieldData"] == {"f2": "named", "f2_2": "unnamed"}

    def test_collection_items_fail_on_missing_node_id(self) -> None:
        # A row with a null primary key component must fail the sync, not merge silently.
        with pytest.raises(KeyError):
            self._run_endpoint(
                "CollectionItems",
                {
                    "getCollections": [{"id": "c1", "name": "Blog"}],
                    "getCollectionFields2": [],
                    "getCollectionItems2": [{"externalId": None, "slug": "s", "fieldData": {}}],
                },
            )

    def test_deployments_rows_paginate(self) -> None:
        pages = {
            None: {"deployments": [{"id": "d1"}], "hasNextPage": True, "cursor": "cur-1"},
            "cur-1": {"deployments": [{"id": "d2"}], "hasNextPage": False},
        }

        def list_deployments(page_size: int, cursor: Optional[str] = None) -> dict[str, Any]:
            assert page_size == DEPLOYMENTS_PAGE_SIZE
            return pages[cursor]

        rows = self._run_endpoint("Deployments", {"listDeployments": list_deployments})
        assert rows == [{"id": "d1"}, {"id": "d2"}]

    def test_locales_and_redirects_rows(self) -> None:
        assert self._run_endpoint("Locales", {"getLocales": [{"id": "l1", "code": "en-US"}]}) == [
            {"id": "l1", "code": "en-US"}
        ]
        assert self._run_endpoint("Redirects", {"getRedirects": [{"id": "r1", "from": "/a", "to": "/b"}]}) == [
            {"id": "r1", "from": "/a", "to": "/b"}
        ]

    def test_every_endpoint_has_a_primary_key(self) -> None:
        assert set(PRIMARY_KEYS) == set(ENDPOINTS)

    def test_source_response_raises_for_invalid_project(self) -> None:
        response = framer_source("not a project", "key", "Project", protocol_version="0.1.29")
        with pytest.raises(FramerAPIError) as exc_info:
            list(cast(Iterable[Any], response.items()))
        assert exc_info.value.code == "INVALID_REQUEST"
