"""Client and row iterators for Framer's Server API.

Framer has no REST API: the official surface is the `framer-api` Node SDK, which talks a
devalue-encoded RPC over a WebSocket (`wss://api.framer.com/channel/headless-plugin`).
This module speaks the same wire protocol: an auth'd WebSocket connect, a
`ready` -> `pluginReadySignal` -> `pluginReadyResponse` handshake, then
`methodInvocation`/`methodResponse` pairs. The protocol version we were built against is
sent as the `sdkVersion` query parameter, exactly like the SDK release it mirrors.
"""

import re
import json
import time
import socket
import http.client
from collections.abc import Callable, Iterator
from typing import Any, Optional, Protocol
from urllib.parse import unquote, urlencode, urljoin, urlsplit

from structlog.types import FilteringBoundLogger
from websockets.exceptions import ConnectionClosed, InvalidMessage, InvalidStatus
from websockets.headers import build_authorization_basic
from websockets.sync.client import connect as websocket_connect
from websockets.uri import Proxy, get_proxy, parse_proxy, parse_uri

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.framer import devalue
from products.warehouse_sources.backend.temporal.data_imports.sources.framer.settings import (
    DEPLOYMENTS_MAX_PAGES,
    DEPLOYMENTS_PAGE_SIZE,
    PRIMARY_KEYS,
)

FRAMER_HEADLESS_WS_URL = "wss://api.framer.com/channel/headless-plugin"

# The server boots a headless instance of the project on connect, which can take a while
# for large projects — the official SDK allows 90s, so we do too.
CONNECT_TIMEOUT_SECONDS = 90
CALL_TIMEOUT_SECONDS = 300
# Large responses arrive pre-chunked by the server, but a single frame can still be big.
MAX_MESSAGE_BYTES = 64 * 1024 * 1024
# Bound on a reassembled chunked message, so a runaway stream fails cleanly instead of
# exhausting worker memory.
MAX_ASSEMBLED_MESSAGE_BYTES = 512 * 1024 * 1024

# Codes the server marks transient (plus its explicit `retryable` flag): a busy headless
# pool or a concurrent-session collision recovers on the next Temporal attempt.
RETRYABLE_ERROR_CODES = {"POOL_EXHAUSTED", "TOKEN_SESSION_LIMIT", "TIMEOUT", "CONNECTION_CLOSED"}

# A raw project id is exactly 20 alphanumerics; project URLs carry `<slug>--<id>`.
_PROJECT_ID_REGEX = re.compile(r"^[A-Za-z0-9]{20}$")
_PROJECT_URL_SEGMENT_REGEX = re.compile(r"^.+--([A-Za-z0-9]+)")


class FramerAPIError(Exception):
    def __init__(self, message: str, code: str = "INTERNAL", retryable: bool = False) -> None:
        super().__init__(f"Framer API error {code}: {message}")
        self.code = code
        self.retryable = retryable


class WebSocketLike(Protocol):
    """The slice of `websockets.sync.client.ClientConnection` the client uses; the seam tests fake."""

    def send(self, message: str) -> None: ...

    def recv(self, timeout: Optional[float] = None) -> Any: ...

    def close(self) -> None: ...


def _tunnel_through_proxy(proxy: Proxy, host: str, port: int) -> socket.socket:
    """Open a CONNECT tunnel to ``host:port`` through an HTTP(S) proxy and return the socket.

    websockets' own proxy support requires an HTTP/1.1 status line on the CONNECT
    response (until v17), but goproxy-based egress proxies such as Smokescreen answer a
    successful CONNECT with ``HTTP/1.0 200 OK``, which websockets rejects as
    "did not receive a valid HTTP response from proxy". ``http.client`` accepts HTTP/1.0,
    so we establish the tunnel ourselves and hand the socket to websockets. This helper
    can be dropped once the pinned websockets version is >= 17.
    """
    connection_class = http.client.HTTPSConnection if proxy.scheme == "https" else http.client.HTTPConnection
    connection = connection_class(proxy.host, proxy.port, timeout=CONNECT_TIMEOUT_SECONDS)
    headers: dict[str, str] = {}
    if proxy.username is not None:
        headers["Proxy-Authorization"] = build_authorization_basic(proxy.username, proxy.password or "")
    connection.set_tunnel(host, port, headers)
    try:
        connection.connect()
    except OSError as e:
        connection.close()
        raise FramerAPIError(
            f"Could not reach Framer through the network proxy ({e}). Try again, and contact support if it keeps failing.",
            code="PROXY",
            retryable=True,
        ) from e
    sock = connection.sock
    # Detach before the connection object goes out of scope, so its close() can't
    # tear down the tunnel we're handing to websockets.
    connection.sock = None
    assert sock is not None  # connect() either sets the socket or raises
    return sock


def parse_project_id(project: str) -> Optional[str]:
    """Resolve a project URL or raw id to the 20-char project id, mirroring the official SDK.

    Accepts the raw id, or any framer.com URL whose path contains `projects/<slug>--<id>`
    (or `projects/<id>`). Returns None when no valid id can be extracted.
    """
    candidate = project.strip()
    if _PROJECT_ID_REGEX.match(candidate):
        return candidate
    try:
        parsed = urlsplit(urljoin("https://framer.com", candidate))
    except ValueError:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    for position, segment in enumerate(segments):
        if segment.lower() == "projects" and position + 1 < len(segments):
            tail = unquote(segments[position + 1])
            match = _PROJECT_URL_SEGMENT_REGEX.match(tail)
            project_id = match.group(1) if match else tail
            if _PROJECT_ID_REGEX.match(project_id):
                return project_id
            return None
    return None


class FramerClient:
    """Synchronous client for the Framer headless WebSocket channel."""

    def __init__(
        self,
        project_id: str,
        api_key: str,
        protocol_version: str,
        url: str = FRAMER_HEADLESS_WS_URL,
        connect_fn: Optional[Callable[..., WebSocketLike]] = None,
    ) -> None:
        self._project_id = project_id
        self._api_key = api_key
        self._protocol_version = protocol_version
        self._url = url
        self._connect_fn = connect_fn or websocket_connect
        self._ws: Optional[WebSocketLike] = None
        self._graceful_disconnect = False
        self._next_invocation_id = 0
        self._chunk_buffers: dict[str, list[str]] = {}

    def __enter__(self) -> "FramerClient":
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def connect(self) -> None:
        query = urlencode({"projectId": self._project_id, "sdkVersion": self._protocol_version})
        url = f"{self._url}?{query}"
        connect_kwargs: dict[str, Any] = {}
        ws_uri = parse_uri(url)
        proxy = get_proxy(ws_uri)
        if proxy is not None:
            proxy_parsed = parse_proxy(proxy)
            if proxy_parsed.scheme in ("http", "https"):
                # Tunnel the CONNECT ourselves because websockets < 17 rejects the
                # HTTP/1.0 success line Smokescreen sends (see _tunnel_through_proxy).
                # Passing a socket makes websockets skip its own proxy handling while
                # still doing TLS against the Framer host. SOCKS proxies fall through
                # to websockets' built-in support.
                connect_kwargs["sock"] = _tunnel_through_proxy(proxy_parsed, ws_uri.host, ws_uri.port)
        try:
            self._ws = self._connect_fn(
                url,
                additional_headers={"Authorization": f"Token {self._api_key}"},
                open_timeout=CONNECT_TIMEOUT_SECONDS,
                max_size=MAX_MESSAGE_BYTES,
                **connect_kwargs,
            )
        except InvalidStatus as e:
            status = e.response.status_code
            if status in (401, 403):
                raise FramerAPIError("Framer rejected the API key", code="UNAUTHORIZED") from e
            raise FramerAPIError(f"Connection rejected with HTTP {status}", code="INTERNAL", retryable=True) from e
        except InvalidMessage as e:
            # The server accepted the TCP/TLS connection but closed it before sending a
            # parseable HTTP response (e.g. an EOF while reading the status line) — a
            # headless-pool hiccup on Framer's side, not a credential or config problem.
            raise FramerAPIError(
                f"Connection closed during handshake: {e}", code="CONNECTION_CLOSED", retryable=True
            ) from e

        deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS
        while True:
            message = self._receive(deadline)
            message_type = message.get("type") if isinstance(message, dict) else None
            if message_type == "ready":
                self._graceful_disconnect = message.get("gracefulDisconnect") is True
                self._send({"type": "pluginReadySignal"})
            elif message_type == "pluginReadyResponse":
                return

    def close(self) -> None:
        if self._ws is None:
            return
        try:
            if self._graceful_disconnect:
                self._send({"type": "client-disconnect"})
        except Exception:
            pass
        try:
            self._ws.close()
        finally:
            self._ws = None

    def call(self, method: str, *args: Any) -> Any:
        invocation_id = self._next_invocation_id
        self._next_invocation_id += 1
        self._send({"type": "methodInvocation", "methodName": method, "id": invocation_id, "args": list(args)})
        deadline = time.monotonic() + CALL_TIMEOUT_SECONDS
        while True:
            message = self._receive(deadline)
            if not isinstance(message, dict):
                continue
            if message.get("type") == "methodResponse" and message.get("id") == invocation_id:
                error = message.get("error")
                if isinstance(error, str):
                    raise FramerAPIError(f"{method}: {error}", code="METHOD_ERROR")
                return message.get("result")
            # Anything else (permissionUpdate, subscription traffic) is irrelevant here.

    def _send(self, message: dict[str, Any]) -> None:
        if self._ws is None:
            raise FramerAPIError("Connection closed", code="CONNECTION_CLOSED", retryable=True)
        self._ws.send(devalue.stringify(message))

    def _receive(self, deadline: float) -> Any:
        while True:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise FramerAPIError("Timed out waiting for a response", code="TIMEOUT", retryable=True)
            if self._ws is None:
                raise FramerAPIError("Connection closed", code="CONNECTION_CLOSED", retryable=True)
            try:
                raw = self._ws.recv(timeout=timeout)
            except TimeoutError:
                raise FramerAPIError("Timed out waiting for a response", code="TIMEOUT", retryable=True)
            except ConnectionClosed as e:
                raise FramerAPIError(f"Connection closed: {e}", code="CONNECTION_CLOSED", retryable=True)

            text = raw.decode() if isinstance(raw, bytes) else raw
            complete = self._assemble_chunks(text)
            if complete is None:
                continue
            message = devalue.parse(complete)
            if isinstance(message, dict) and message.get("type") == "error":
                code = str(message.get("code") or "INTERNAL")
                raise FramerAPIError(
                    str(message.get("message") or "Server error"),
                    code=code,
                    retryable=message.get("retryable") is True or code in RETRYABLE_ERROR_CODES,
                )
            return message

    def _assemble_chunks(self, text: str) -> Optional[str]:
        """Reassemble the server's chunked-message envelopes; `seq == -1` marks the final chunk."""
        if not text.startswith('{"$chunk":'):
            return text
        try:
            envelope = json.loads(text)
        except ValueError:
            return text
        if not isinstance(envelope, dict) or envelope.get("$chunk") != 1:
            return text
        chunk_id = envelope.get("id")
        sequence = envelope.get("seq")
        if not isinstance(chunk_id, str) or not isinstance(sequence, int):
            return text
        buffer = self._chunk_buffers.setdefault(chunk_id, [])
        buffer.append(str(envelope.get("data") or ""))
        if sum(len(part) for part in buffer) > MAX_ASSEMBLED_MESSAGE_BYTES:
            self._chunk_buffers.clear()
            raise FramerAPIError(
                f"Chunked message exceeded {MAX_ASSEMBLED_MESSAGE_BYTES} bytes", code="MESSAGE_TOO_LARGE"
            )
        if sequence == -1:
            del self._chunk_buffers[chunk_id]
            return "".join(buffer)
        return None


def validate_credentials(project: str, api_key: str, protocol_version: str) -> tuple[bool, Optional[str]]:
    project_id = parse_project_id(project)
    if project_id is None:
        return (
            False,
            "Invalid Framer project URL or ID. Paste your project URL (https://framer.com/projects/...) or the project ID.",
        )
    try:
        with FramerClient(project_id, api_key, protocol_version) as client:
            client.call("getProjectInfo2")
        return True, None
    except FramerAPIError as e:
        if e.code == "UNAUTHORIZED":
            return (
                False,
                "Framer rejected the API key for this project. Generate an API key in the project's Site Settings → General and try again.",
            )
        return False, str(e)
    except Exception as e:
        return False, f"Could not connect to Framer: {e}"


def _without_class_marker(node: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in node.items() if key != "__class"}


def _as_dict_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _project_rows(client: FramerClient) -> Iterator[list[dict[str, Any]]]:
    info = client.call("getProjectInfo2")
    row = dict(info) if isinstance(info, dict) else {}
    publish_info = client.call("getPublishInfo")
    if isinstance(publish_info, dict):
        row["production"] = publish_info.get("production")
        row["staging"] = publish_info.get("staging")
    if row:
        yield [row]


def _pages_rows(client: FramerClient) -> Iterator[list[dict[str, Any]]]:
    # Direct access so a malformed root fails the sync instead of yielding an empty table.
    root_id = client.call("getCanvasRoot")["id"]
    nodes = _as_dict_rows(client.call("getNodesWithType", root_id, "WebPageNode"))
    rows = [_without_class_marker(node) for node in nodes]
    if rows:
        yield rows


def _collections_rows(client: FramerClient) -> Iterator[list[dict[str, Any]]]:
    rows = []
    for collection in _as_dict_rows(client.call("getCollections")):
        fields = _as_dict_rows(client.call("getCollectionFields2", collection["id"], True))
        rows.append({**collection, "fields": fields})
    if rows:
        yield rows


def _readable_field_data(field_data: Any, field_names: dict[Any, str]) -> dict[str, Any]:
    """Key field values by display name, keeping every entry when names collide.

    A colliding display name falls back to the unique field id; if that id in turn matches
    another field's display name, a numeric suffix disambiguates so no value is overwritten.
    """
    readable: dict[str, Any] = {}
    if not isinstance(field_data, dict):
        return readable
    for field_id, entry in field_data.items():
        key = field_names.get(field_id) or str(field_id)
        if key in readable:
            key = str(field_id)
            suffix = 2
            while key in readable:
                key = f"{field_id}_{suffix}"
                suffix += 1
        readable[key] = entry.get("value") if isinstance(entry, dict) else entry
    return readable


def _collection_item_row(
    item: dict[str, Any], collection: dict[str, Any], field_names: dict[Any, str]
) -> dict[str, Any]:
    return {
        # `externalId` is only set on plugin-managed items; `nodeId` is the required
        # identifier, accessed directly so a malformed record fails the sync instead of
        # writing a null primary key component.
        "id": item.get("externalId") or item["nodeId"],
        "nodeId": item["nodeId"],
        "collectionId": collection["id"],
        "collectionName": collection.get("name"),
        "slug": item.get("slug"),
        "slugByLocale": item.get("slugByLocale"),
        "draft": item.get("draft", False),
        "createdAt": item.get("createdAt"),
        "updatedAt": item.get("updatedAt"),
        "fieldData": _readable_field_data(item.get("fieldData"), field_names),
    }


def _collection_items_rows(client: FramerClient) -> Iterator[list[dict[str, Any]]]:
    for collection in _as_dict_rows(client.call("getCollections")):
        collection_id = collection["id"]
        fields = _as_dict_rows(client.call("getCollectionFields2", collection_id, True))
        field_names = {field.get("id"): str(field.get("name")) for field in fields if field.get("name")}
        items = _as_dict_rows(client.call("getCollectionItems2", collection_id))
        rows = [_collection_item_row(item, collection, field_names) for item in items]
        if rows:
            yield rows


def _locales_rows(client: FramerClient) -> Iterator[list[dict[str, Any]]]:
    rows = _as_dict_rows(client.call("getLocales"))
    if rows:
        yield rows


def _redirects_rows(client: FramerClient) -> Iterator[list[dict[str, Any]]]:
    rows = _as_dict_rows(client.call("getRedirects"))
    if rows:
        yield rows


def _deployments_rows(client: FramerClient, logger: Optional[FilteringBoundLogger]) -> Iterator[list[dict[str, Any]]]:
    cursor: Optional[str] = None
    for _page_number in range(DEPLOYMENTS_MAX_PAGES):
        if cursor is None:
            page = client.call("listDeployments", DEPLOYMENTS_PAGE_SIZE)
        else:
            page = client.call("listDeployments", DEPLOYMENTS_PAGE_SIZE, cursor)
        if not isinstance(page, dict):
            return
        deployments = _as_dict_rows(page.get("deployments"))
        if deployments:
            yield deployments
        if not page.get("hasNextPage"):
            return
        cursor = page.get("cursor")
        if not cursor:
            return
    if logger:
        logger.warning("Framer deployments page cap reached", max_pages=DEPLOYMENTS_MAX_PAGES)


def _endpoint_rows(
    client: FramerClient, endpoint: str, logger: Optional[FilteringBoundLogger]
) -> Iterator[list[dict[str, Any]]]:
    if endpoint == "Project":
        yield from _project_rows(client)
    elif endpoint == "Pages":
        yield from _pages_rows(client)
    elif endpoint == "Collections":
        yield from _collections_rows(client)
    elif endpoint == "CollectionItems":
        yield from _collection_items_rows(client)
    elif endpoint == "Locales":
        yield from _locales_rows(client)
    elif endpoint == "Redirects":
        yield from _redirects_rows(client)
    elif endpoint == "Deployments":
        yield from _deployments_rows(client, logger)
    else:
        raise FramerAPIError(f"Unknown endpoint: {endpoint}", code="INVALID_REQUEST")


def framer_source(
    project: str,
    api_key: str,
    endpoint: str,
    protocol_version: str,
    logger: Optional[FilteringBoundLogger] = None,
) -> SourceResponse:
    project_id = parse_project_id(project)

    def items() -> Iterator[list[dict[str, Any]]]:
        if project_id is None:
            raise FramerAPIError(f"Invalid Framer project URL or ID: {project}", code="INVALID_REQUEST")
        with FramerClient(project_id, api_key, protocol_version) as client:
            yield from _endpoint_rows(client, endpoint, logger)

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=PRIMARY_KEYS[endpoint],
    )
