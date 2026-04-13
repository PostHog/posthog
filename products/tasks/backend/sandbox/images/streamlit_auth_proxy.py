"""Auth proxy for Streamlit apps in Modal sandboxes.

Listens on port 8080 (Modal connect token port), reverse proxies to Streamlit on localhost:8501.
Validates PostHog OAuth access tokens via the /oauth/introspect endpoint on every request,
caching introspection results by token hash to avoid per-request overhead.

Modal requires `_modal_connect_token` on every HTTP request through the tunnel, but strips
it before forwarding to us. The backend duplicates the token as `_posthog_modal_token` which
passes through. We capture that token PER REQUEST and inject a JS shim into HTML responses
that patches fetch/XHR/WebSocket/script.src to add both `_modal_connect_token` AND
`_posthog_token` to all same-host browser sub-requests. This keeps every request authenticated
end-to-end (Modal tunnel AND our proxy) without relying on session cookies (which don't work
reliably in cross-origin iframes).

Bridge endpoint (port 8181, 127.0.0.1-only): exposes /_bridge/query, used by the in-sandbox
posthog_apps.query() shim to run HogQL via PostHog. The bridge forwarder reads its bearer
token from /run/bridge_token at startup, then unlinks the file. The token is never available
through the tunneled port.
"""

import os
import re
import sys
import html
import json
import time
import asyncio
import hashlib
import logging
from urllib.parse import parse_qs, urlencode

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("auth_proxy")

LISTEN_PORT = 8080
BRIDGE_LISTEN_PORT = 8181  # 127.0.0.1-only; never tunneled by Modal
UPSTREAM = "http://localhost:8501"
POSTHOG_SITE_URL = os.environ.get("POSTHOG_SITE_URL", "")
# POSTHOG_TEAM_ID and POSTHOG_STREAMLIT_CLIENT_ID are intentionally read inside
# create_app() (not at module import) so that:
# 1. Missing or invalid values trigger a startup RuntimeError instead of
#    silently falling back to values that would match no real token, and
# 2. Tests can call create_app() in different environment states without
#    having to reload the module.
BRIDGE_TOKEN_PATH = "/run/bridge_token"

INTROSPECTION_CACHE_TTL = 60.0  # 60s — short revocation window without per-request overhead
INTROSPECTION_TIMEOUT = ClientTimeout(total=10)
INTROSPECTION_CACHE_MAX_ENTRIES = 1000
INTROSPECTION_CIRCUIT_THRESHOLD = 3
INTROSPECTION_CIRCUIT_OPEN_SECONDS = 30.0
STREAM_CHUNK_SIZE = 64 * 1024
# Hard cap on client uploads proxied upstream. Anything larger than this is
# almost certainly an attempt to exhaust the sandbox's memory — we refuse with
# 413 before reading the body. The previous `await request.read()` path would
# buffer the full body before forwarding, turning a 1 GB upload into 1 GB of
# resident memory per in-flight request.
MAX_REQUEST_BODY_BYTES = 256 * 1024 * 1024  # 256 MB
BRIDGE_QUERY_MAX_BODY_BYTES = 16 * 1024  # match the server-side limit
BRIDGE_QUERY_TIMEOUT = ClientTimeout(total=60)

# OTEL log export config. Django sets OTEL_EXPORTER_OTLP_LOGS_ENDPOINT explicitly
# at sandbox-create time (region-aware — cloud prod ships to PH-on-PH). The
# fallback below is for standalone test runs where the env var isn't wired up.
OTEL_SERVICE_NAME_DEFAULT = "streamlit-auth-proxy"
OTEL_LOG_PATH = "/i/v1/logs"  # Caddy route on the PostHog ingress -> capture-logs:4318

HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
    }
)

# Headers we strip on the way *upstream* (in addition to HOP_BY_HOP). The Referer
# carries the full token-bearing iframe URL, so dropping it prevents user code
# from reading our auth tokens via document.referrer / Referer-driven analytics.
STRIP_UPSTREAM = frozenset({"referer"})

# JS shim injected into <head> of HTML responses. Patches fetch, XMLHttpRequest,
# WebSocket, and dynamic element src/href setters to append both tokens on all
# same-host requests. Covers webpack dynamic chunk loading (script.src) and
# Streamlit's WebSocket. The %s placeholder is filled via json.dumps for safe
# JS string embedding, then escaped for </script> breakout.
_TOKEN_INJECTION_JS_TEMPLATE = """<script>
(function(){
  var MK="_modal_connect_token",MV=%s,PK="_posthog_token",PV=%s;
  function a(u){
    try{var o=new URL(u,location.origin);
    if(o.hostname===location.hostname){
      if(!o.searchParams.has(MK)){o.searchParams.set(MK,MV)}
      if(!o.searchParams.has(PK)){o.searchParams.set(PK,PV)}
    }
    return o.toString()}catch(e){return u}
  }
  var F=window.fetch;
  window.fetch=function(i,n){
    if(typeof i==="string"){i=a(i)}
    else if(i instanceof Request){i=new Request(a(i.url),i)}
    return F.call(this,i,n)};
  var X=XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open=function(m,u){arguments[1]=a(u);return X.apply(this,arguments)};
  var W=window.WebSocket;
  window.WebSocket=function(u,p){u=a(u);return p!==undefined?new W(u,p):new W(u)};
  window.WebSocket.prototype=W.prototype;
  window.WebSocket.CONNECTING=W.CONNECTING;
  window.WebSocket.OPEN=W.OPEN;
  window.WebSocket.CLOSING=W.CLOSING;
  window.WebSocket.CLOSED=W.CLOSED;
  function patchSrc(El,prop){
    var d=Object.getOwnPropertyDescriptor(El.prototype,prop);
    if(d&&d.set){Object.defineProperty(El.prototype,prop,{
      set:function(v){d.set.call(this,a(v))},
      get:d.get,configurable:true,enumerable:true
    })}
  }
  patchSrc(HTMLScriptElement,"src");
  patchSrc(HTMLLinkElement,"href");
  patchSrc(HTMLImageElement,"src");
  patchSrc(HTMLIFrameElement,"src");
})();
</script>"""

_AUTH_EXEMPT_PREFIXES = ("/static/", "/favicon.", "/healthz", "/_stcore/host-config")

# Introspection result cache: token_hash -> (result_dict, expires_at_epoch).
# Keyed by SHA-256 hash so tokens never appear in memory dumps or logs.
# Bounded to INTROSPECTION_CACHE_MAX_ENTRIES; oldest expiries are evicted first.
_introspection_cache: dict[str, tuple[dict, float]] = {}

# Circuit breaker state for the introspection upstream. After
# INTROSPECTION_CIRCUIT_THRESHOLD consecutive failures, fast-fail every request
# for INTROSPECTION_CIRCUIT_OPEN_SECONDS seconds before retrying upstream.
_introspection_circuit: dict[str, float] = {"failures": 0.0, "open_until": 0.0}

# Bearer token used for the in-sandbox bridge → PostHog HogQL hop. Loaded once
# at startup from /run/bridge_token, which is then unlinked. Stays in process
# memory only — never re-read from disk, never logged, never sent over the
# tunneled port (the /_bridge/query route is bound to 127.0.0.1 on a separate
# aiohttp app on BRIDGE_LISTEN_PORT).
_bridge_token: str | None = None

# Holds the OTEL LoggerProvider so we can force_flush() on shutdown. Typed as
# `object` because the real type (opentelemetry.sdk._logs.LoggerProvider) may
# not be importable at module load (the whole OTEL setup is optional).
_logger_provider: object | None = None


def _resolve_otel_endpoint() -> str | None:
    """Return the OTLP logs endpoint, or None if log export should be skipped.

    Preference order:
      1. OTEL_EXPORTER_OTLP_LOGS_ENDPOINT (standard OTEL env var, full URL — set
         by Django at sandbox-create time for region-aware routing)
      2. OTEL_EXPORTER_OTLP_ENDPOINT (standard OTEL env var, base URL)
      3. POSTHOG_SITE_URL + /i/v1/logs (fallback for standalone test runs)
    """
    explicit = os.environ.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT")
    if explicit:
        return explicit
    base = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if base:
        return base.rstrip("/") + OTEL_LOG_PATH
    if POSTHOG_SITE_URL:
        return POSTHOG_SITE_URL.rstrip("/") + OTEL_LOG_PATH
    return None


class _OtelAttributeSanitizer(logging.Filter):
    """Stringify Mapping-valued LogRecord fields before they reach OTLP.

    OTEL attributes only accept bool / str / bytes / int / float or sequences
    of those. aiohttp's access logger attaches `request_header` (a dict) and
    other mapping-typed extras on every request, which triggers an "Invalid
    type dict for attribute" warning from the OTEL SDK on each log call. We
    proactively repr() any Mapping so the handler receives a plain string.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        from collections.abc import Mapping

        for key, value in list(record.__dict__.items()):
            if isinstance(value, Mapping):
                record.__dict__[key] = repr(value)
        return True


def _setup_otel_logging() -> None:
    """Wire stdlib logging into OTLP via a LoggingHandler on the root logger.

    Safe to call once at startup. Any failure (missing SDK, bad env, exporter
    init error) is swallowed — the proxy must never fail to serve traffic
    because telemetry is broken.
    """
    global _logger_provider

    endpoint = _resolve_otel_endpoint()
    if endpoint is None:
        log.info("otel: no endpoint configured, skipping log export")
        return

    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
    except ImportError as exc:
        log.warning("otel: SDK not available, skipping log export (%s)", exc)
        return

    try:
        resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", OTEL_SERVICE_NAME_DEFAULT)})
        provider = LoggerProvider(resource=resource)
        exporter = OTLPLogExporter(endpoint=endpoint)
        provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
        set_logger_provider(provider)

        handler = LoggingHandler(level=logging.INFO, logger_provider=provider)
        handler.addFilter(_OtelAttributeSanitizer())
        logging.getLogger().addHandler(handler)

        _logger_provider = provider
        log.info("otel: logging enabled endpoint=%s", endpoint)
    except Exception:
        log.exception("otel: failed to initialize, falling back to stderr only")


async def _shutdown_otel(app: web.Application) -> None:
    """Flush pending log batches on graceful shutdown."""
    if _logger_provider is not None:
        try:
            _logger_provider.force_flush(timeout_millis=5000)  # type: ignore[attr-defined]
            _logger_provider.shutdown()  # type: ignore[attr-defined]
        except Exception:
            log.warning("otel: flush on shutdown failed", exc_info=True)


def _load_bridge_token() -> None:
    """Read the bridge bearer token from /run/bridge_token, then unlink it.

    Why a file (not env var): env vars leak via /proc/<pid>/environ to anything
    sharing the uid in the sandbox. We open the file once at startup, hold the
    fd, immediately unlink, and read into a module-level variable that never
    leaves process memory.
    """
    global _bridge_token

    try:
        fd = os.open(BRIDGE_TOKEN_PATH, os.O_RDONLY)
    except FileNotFoundError:
        log.warning("bridge: token file missing at %s; /_bridge/query will return 503", BRIDGE_TOKEN_PATH)
        return
    except OSError:
        log.exception("bridge: failed to open token file")
        return

    try:
        with os.fdopen(fd, "rb") as fh:
            data = fh.read()
    except OSError:
        log.exception("bridge: failed to read token file")
        return

    try:
        os.unlink(BRIDGE_TOKEN_PATH)
    except OSError:
        log.warning("bridge: failed to unlink token file (continuing)", exc_info=True)

    token = data.decode("utf-8", errors="replace").strip()
    if not token:
        log.warning("bridge: token file was empty")
        return

    _bridge_token = token
    log.info("bridge: token loaded into memory and unlinked from disk")


def _filter_headers(headers, *, upstream: bool = False):
    if upstream:
        deny = HOP_BY_HOP | STRIP_UPSTREAM
    else:
        deny = HOP_BY_HOP
    return {k: v for k, v in headers.items() if k.lower() not in deny}


def _strip_auth_params(query_string: str) -> str:
    """Remove auth tokens from query string before proxying to upstream Streamlit."""
    params = parse_qs(query_string, keep_blank_values=True)
    params.pop("_posthog_token", None)
    params.pop("_posthog_modal_token", None)
    params.pop("_modal_connect_token", None)
    flat = {k: v[0] if len(v) == 1 else v for k, v in params.items()}
    return urlencode(flat, doseq=True)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _evict_introspection_cache_if_full() -> None:
    """If the cache is at capacity, drop the entries with the soonest expiry.

    We sort by expiry rather than LRU because the natural lifecycle of these
    entries is "valid until expiry, then evict on next miss". Soonest-expiry
    eviction matches that lifecycle and avoids needing to maintain a separate
    access-order data structure.
    """
    if len(_introspection_cache) < INTROSPECTION_CACHE_MAX_ENTRIES:
        return
    # First, sweep entries that are already expired.
    now = time.monotonic()
    expired = [k for k, (_, exp) in _introspection_cache.items() if exp <= now]
    for key in expired:
        _introspection_cache.pop(key, None)
    if len(_introspection_cache) < INTROSPECTION_CACHE_MAX_ENTRIES:
        return
    # Still full — drop the soonest-to-expire 10% so we don't thrash on every insert.
    by_expiry = sorted(_introspection_cache.items(), key=lambda kv: kv[1][1])
    drop_count = max(1, INTROSPECTION_CACHE_MAX_ENTRIES // 10)
    for key, _ in by_expiry[:drop_count]:
        _introspection_cache.pop(key, None)


def _record_introspection_failure() -> None:
    _introspection_circuit["failures"] += 1
    if _introspection_circuit["failures"] >= INTROSPECTION_CIRCUIT_THRESHOLD:
        _introspection_circuit["open_until"] = time.monotonic() + INTROSPECTION_CIRCUIT_OPEN_SECONDS
        log.warning(
            "introspect: circuit opened after %d consecutive failures",
            int(_introspection_circuit["failures"]),
        )


def _record_introspection_success() -> None:
    if _introspection_circuit["failures"] or _introspection_circuit["open_until"]:
        _introspection_circuit["failures"] = 0
        _introspection_circuit["open_until"] = 0.0


def _circuit_open() -> bool:
    return time.monotonic() < _introspection_circuit["open_until"]


async def _introspect_token(
    session: ClientSession,
    token: str,
    *,
    team_id: int,
    expected_client_id: str,
) -> dict | None:
    """Validate an OAuth token via PostHog's introspection endpoint, with caching.

    Uses self-introspection: the token introspects itself, so no extra credentials
    or 'introspection' scope is needed. Results are cached for INTROSPECTION_CACHE_TTL
    seconds keyed by token hash.

    Rejects tokens that fail any of:
      - scoped_teams does not include team_id (per-sandbox team binding)
      - application client_id does not match expected_client_id (cross-application
        token rejection — tokens minted against any other first-party OAuth app
        must not unlock this sandbox even if they share team scope)

    A circuit breaker fast-fails all requests after a few consecutive upstream
    failures so we don't pile load on a degraded PostHog API; the breaker
    half-opens after INTROSPECTION_CIRCUIT_OPEN_SECONDS.
    """
    if not POSTHOG_SITE_URL:
        log.warning("introspect: POSTHOG_SITE_URL not set, rejecting token")
        return None

    now = time.monotonic()
    token_hash = _hash_token(token)

    # Cache hit
    cached = _introspection_cache.get(token_hash)
    if cached is not None:
        result, expires_at = cached
        if now < expires_at:
            log.debug("introspect: cache hit hash=%s", token_hash[:8])
            return result
        _introspection_cache.pop(token_hash, None)

    if _circuit_open():
        log.warning("introspect: circuit open, rejecting token without upstream call")
        return None

    url = f"{POSTHOG_SITE_URL}/oauth/introspect/"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    body = f"token={token}"

    log.debug("introspect: cache miss hash=%s, calling %s", token_hash[:8], url)
    try:
        async with session.post(url, headers=headers, data=body, timeout=INTROSPECTION_TIMEOUT) as resp:
            raw_body = await resp.read()
            if resp.status != 200:
                log.warning("introspect: non-200 status=%d", resp.status)
                _record_introspection_failure()
                return None
            try:
                data = json.loads(raw_body)
            except (ValueError, json.JSONDecodeError):
                log.warning("introspect: invalid JSON")
                _record_introspection_failure()
                return None
            if not data.get("active"):
                log.warning("introspect: token not active")
                _record_introspection_success()  # upstream is healthy; this token is just bad
                return None
            scoped_teams = data.get("scoped_teams") or []
            if not scoped_teams:
                log.warning("introspect: token missing scoped_teams")
                _record_introspection_success()
                return None
            # Per-sandbox team binding: refuse tokens that don't include the team
            # this sandbox was minted for. Without this check, ANY OAuth token
            # the proxy can introspect (any team in PostHog) would unlock the app.
            if team_id not in scoped_teams:
                log.warning(
                    "introspect: token team mismatch expected=%d scoped=%s",
                    team_id,
                    scoped_teams,
                )
                _record_introspection_success()
                return None
            # Per-application binding: even a token from a first-party PostHog
            # OAuth app that *does* carry matching scoped_teams must still be
            # rejected if it was minted against a different application. This
            # prevents e.g. an MCP-app token with query:read scope from
            # unlocking a streamlit sandbox.
            token_client_id = data.get("client_id")
            if token_client_id != expected_client_id:
                log.warning(
                    "introspect: token client_id mismatch expected=%s got=%s",
                    expected_client_id,
                    token_client_id,
                )
                _record_introspection_success()
                return None
            _evict_introspection_cache_if_full()
            _introspection_cache[token_hash] = (data, now + INTROSPECTION_CACHE_TTL)
            _record_introspection_success()
            log.debug("introspect: success user_id=%s", data.get("user_id"))
            return data
    except Exception:
        log.exception("introspect: request failed")
        _record_introspection_failure()
        return None


def _inject_token_into_html(body: bytes, modal_token: str, posthog_token: str) -> bytes:
    """Inject both tokens into Streamlit HTML so browser sub-requests carry them.

    1. Rewrite relative/absolute href/src attributes to include both tokens
    2. Inject a JS shim after <head> that patches fetch/XHR/WebSocket/element.src setters
    """
    text = body.decode("utf-8", errors="replace")

    modal_token_attr = html.escape(modal_token, quote=True)
    posthog_token_attr = html.escape(posthog_token, quote=True)

    def _replace(m: re.Match) -> str:
        attr = m.group(1)
        quote = m.group(2)
        url = m.group(3)
        close_quote = m.group(4)
        sep = "&" if "?" in url else "?"
        return (
            f"{attr}{quote}{url}{sep}"
            f"_modal_connect_token={modal_token_attr}&_posthog_token={posthog_token_attr}{close_quote}"
        )

    text = re.sub(r'((?:href|src)=)(["\'])(\.?/[^"\']*?)(\2)', _replace, text)

    # json.dumps escapes quotes/backslashes; also escape </ to prevent </script> breakout
    modal_js = json.dumps(modal_token).replace("</", "<\\/")
    posthog_js = json.dumps(posthog_token).replace("</", "<\\/")
    js_shim = _TOKEN_INJECTION_JS_TEMPLATE % (modal_js, posthog_js)
    text = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + js_shim, text, count=1)

    return text.encode("utf-8")


async def healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def proxy_handler(request: web.Request) -> web.StreamResponse:
    path = request.path

    # Static assets bypass auth — they're public Streamlit bundles. Defense-in-depth:
    # the JS shim injects tokens into all same-host URLs, so in normal flow these
    # requests reach us with _posthog_token anyway.
    if any(path.startswith(p) for p in _AUTH_EXEMPT_PREFIXES):
        return await _proxy_to_upstream(request)

    token = request.query.get("_posthog_token")
    if not token:
        log.warning("request: no _posthog_token in query (%s %s)", request.method, path)
        return web.Response(status=401, text="Authentication required")

    session = request.app["client_session"]
    introspection = await _introspect_token(
        session,
        token,
        team_id=request.app["posthog_team_id"],
        expected_client_id=request.app["posthog_streamlit_client_id"],
    )
    if not introspection:
        return web.Response(status=403, text="Invalid or expired token")

    return await _proxy_to_upstream(request)


async def _proxy_to_upstream(request: web.Request) -> web.StreamResponse:
    path = request.match_info.get("path", "")
    target = f"{UPSTREAM}/{path}"
    qs = _strip_auth_params(request.query_string)
    if qs:
        target = f"{target}?{qs}"

    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await _proxy_websocket(request, target)

    return await _proxy_http(request, target)


async def _proxy_http(request: web.Request, target: str) -> web.StreamResponse:
    client_session: ClientSession = request.app["client_session"]
    headers = _filter_headers(request.headers, upstream=True)
    posthog_token = request.query.get("_posthog_token")
    # Per-request capture of the modal connect token (passed through by Modal as
    # _posthog_modal_token). No module-level state — every HTML response that
    # injects gets the token from THIS request.
    modal_connect_token = request.query.get("_posthog_modal_token")

    # Refuse oversized uploads before touching the body. The Content-Length
    # header is advisory (chunked transfers don't have one), but when it's
    # present it's the cheapest possible guard.
    content_length = request.content_length
    if content_length is not None and content_length > MAX_REQUEST_BODY_BYTES:
        return web.Response(status=413, text="Request body too large")

    # Stream the request body upstream chunk-by-chunk via aiohttp's StreamReader
    # instead of buffering the whole thing. A non-HTML upload that was 500 MB
    # used to be fully resident in this process before the upstream got a byte.
    body_stream = request.content if request.can_read_body else None

    async with client_session.request(
        method=request.method,
        url=target,
        headers=headers,
        data=body_stream,
        allow_redirects=False,
    ) as resp:
        response_headers = _filter_headers(resp.headers)
        # aiohttp auto-decompresses gzip; drop Content-Encoding so the client
        # doesn't try to decompress the already-plain body.
        response_headers.pop("Content-Encoding", None)
        # Don't leak the iframe URL (which carries _posthog_token) via outbound
        # links or analytics on the page itself.
        response_headers["Referrer-Policy"] = "no-referrer"

        content_type = resp.headers.get("content-type", "")
        is_html = "text/html" in content_type

        # HTML responses: buffer + inject token shim
        if is_html and modal_connect_token and posthog_token:
            body = await resp.read()
            body = _inject_token_into_html(body, modal_connect_token, posthog_token)
            response_headers["Content-Length"] = str(len(body))
            return web.Response(status=resp.status, body=body, headers=response_headers)

        # Non-HTML: stream the body to avoid buffering large payloads in memory
        response_headers.pop("Content-Length", None)
        stream = web.StreamResponse(status=resp.status, headers=response_headers)
        await stream.prepare(request)
        async for chunk in resp.content.iter_chunked(STREAM_CHUNK_SIZE):
            await stream.write(chunk)
        await stream.write_eof()
        return stream


async def _proxy_websocket(request: web.Request, target: str) -> web.WebSocketResponse:
    protocols = request.headers.getall("Sec-WebSocket-Protocol", [])
    all_protocols = []
    for p in protocols:
        all_protocols.extend(s.strip() for s in p.split(",") if s.strip())

    ws_client = web.WebSocketResponse(protocols=tuple(all_protocols))
    await ws_client.prepare(request)

    ws_target = target.replace("http://", "ws://", 1).replace("https://", "wss://", 1)

    client_session: ClientSession = request.app["client_session"]
    async with client_session.ws_connect(ws_target, protocols=tuple(all_protocols)) as ws_upstream:

        async def forward_client_to_upstream():
            async for msg in ws_client:
                if msg.type == WSMsgType.TEXT:
                    await ws_upstream.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await ws_upstream.send_bytes(msg.data)
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    break

        async def forward_upstream_to_client():
            async for msg in ws_upstream:
                if msg.type == WSMsgType.TEXT:
                    await ws_client.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await ws_client.send_bytes(msg.data)
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    break

        await asyncio.gather(
            forward_client_to_upstream(),
            forward_upstream_to_client(),
            return_exceptions=True,
        )

    return ws_client


# ---------- Bridge sub-app (port 8181, 127.0.0.1-only) ----------


async def _bridge_query_handler(request: web.Request) -> web.Response:
    """Forward in-sandbox HogQL queries from posthog_apps.query() to PostHog.

    The bearer token (loaded once at startup, file unlinked) is mediated here so
    user code never sees it. The route is bound to 127.0.0.1 on a separate port
    that is not tunneled by Modal.
    """
    if _bridge_token is None:
        return web.json_response({"error": "Bridge not configured."}, status=503)
    if not POSTHOG_SITE_URL:
        return web.json_response({"error": "Bridge not configured."}, status=503)

    body_bytes = await request.read()
    if len(body_bytes) > BRIDGE_QUERY_MAX_BODY_BYTES:
        return web.json_response({"error": "Request body too large."}, status=413)

    try:
        payload = json.loads(body_bytes)
    except (ValueError, json.JSONDecodeError):
        return web.json_response({"error": "Invalid JSON body."}, status=400)

    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        return web.json_response({"error": "Missing or empty 'query' field."}, status=400)

    target = f"{POSTHOG_SITE_URL.rstrip('/')}/api/streamlit_bridge/query/"
    headers = {
        "Authorization": f"Bearer {_bridge_token}",
        "Content-Type": "application/json",
    }
    client_session: ClientSession = request.app["client_session"]
    try:
        async with client_session.post(
            target,
            headers=headers,
            data=json.dumps({"query": query}).encode("utf-8"),
            timeout=BRIDGE_QUERY_TIMEOUT,
        ) as resp:
            data = await resp.read()
            return web.Response(
                status=resp.status,
                body=data,
                content_type=resp.headers.get("content-type", "application/json"),
            )
    except Exception:
        log.exception("bridge: forward request failed")
        return web.json_response({"error": "Bridge upstream failed."}, status=502)


async def _bridge_healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def _create_bridge_app() -> web.Application:
    bridge_app = web.Application()
    bridge_app.router.add_get("/healthz", _bridge_healthz)
    bridge_app.router.add_post("/_bridge/query", _bridge_query_handler)
    bridge_app.on_startup.append(_start_client_session)
    bridge_app.on_cleanup.append(_close_client_session)
    return bridge_app


# ---------- Main proxy app (port 8080, tunneled) ----------


async def _start_client_session(app: web.Application) -> None:
    app["client_session"] = ClientSession()


async def _close_client_session(app: web.Application) -> None:
    session: ClientSession | None = app.get("client_session")
    if session is not None:
        await session.close()


def _read_required_config() -> tuple[int, str]:
    """Read the two per-sandbox config values that MUST be set for auth to work.

    Fails loudly (RuntimeError) at startup rather than silently. Prior code
    defaulted POSTHOG_TEAM_ID to 0 and then guarded the mismatch check with
    `if POSTHOG_TEAM_ID and ...` — a bug where a misconfigured sandbox would
    silently accept ANY team's token. We now refuse to even start the proxy
    if either value is missing.
    """
    team_id_raw = os.environ.get("POSTHOG_TEAM_ID", "").strip()
    try:
        team_id = int(team_id_raw)
    except ValueError:
        team_id = 0
    if team_id <= 0:
        raise RuntimeError(f"POSTHOG_TEAM_ID env var must be a positive integer (got {team_id_raw!r})")

    client_id = os.environ.get("POSTHOG_STREAMLIT_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError("POSTHOG_STREAMLIT_CLIENT_ID env var must be set")

    return team_id, client_id


def create_app() -> web.Application:
    # OTEL setup runs synchronously before the event loop starts. The
    # BatchLogRecordProcessor spawns its own background thread, so it doesn't
    # need an aiohttp app to be running.
    _setup_otel_logging()
    # Read the bridge token from /run/bridge_token, then unlink the file.
    _load_bridge_token()

    # Read per-sandbox config from env. Raises if either value is missing so a
    # misconfigured sandbox exits immediately rather than accepting bad tokens.
    team_id, client_id = _read_required_config()

    app = web.Application()
    app["posthog_team_id"] = team_id
    app["posthog_streamlit_client_id"] = client_id
    app.router.add_get("/healthz", healthz)
    app.router.add_route("*", "/{path:.*}", proxy_handler)
    app.on_startup.append(_start_client_session)
    app.on_cleanup.append(_close_client_session)
    app.on_cleanup.append(_shutdown_otel)
    return app


async def _run_both_apps(
    main_app: web.Application,
    bridge_app: web.Application,
    main_port: int,
    bridge_port: int,
) -> None:
    """Serve the main proxy on 0.0.0.0:main_port and the bridge on 127.0.0.1:bridge_port.

    Two aiohttp apps share one event loop, but listen on different sockets so
    Modal's tunnel only ever exposes the main proxy port.
    """
    main_runner = web.AppRunner(main_app)
    bridge_runner = web.AppRunner(bridge_app)
    await main_runner.setup()
    await bridge_runner.setup()

    main_site = web.TCPSite(main_runner, host="0.0.0.0", port=main_port)
    bridge_site = web.TCPSite(bridge_runner, host="127.0.0.1", port=bridge_port)
    await main_site.start()
    await bridge_site.start()
    log.info(
        "auth proxy listening on 0.0.0.0:%d, bridge on 127.0.0.1:%d SITE_URL=%s",
        main_port,
        bridge_port,
        POSTHOG_SITE_URL,
    )

    # Park forever — runners shut down via signals delivered to the loop.
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await main_runner.cleanup()
        await bridge_runner.cleanup()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else LISTEN_PORT
    main_app = create_app()
    bridge_app = _create_bridge_app()
    try:
        asyncio.run(_run_both_apps(main_app, bridge_app, port, BRIDGE_LISTEN_PORT))
    except KeyboardInterrupt:
        pass
