"""Auth proxy for Streamlit apps in Modal sandboxes.

Listens on port 8080 (Modal connect token port), reverse proxies to Streamlit on localhost:8501.
Modal validates the connect token and injects X-Verified-User-Data header.
This proxy validates that header exists as defense-in-depth.
"""

import sys

from aiohttp import ClientSession, WSMsgType, web

LISTEN_PORT = 8080
UPSTREAM = "http://localhost:8501"
VERIFIED_HEADER = "X-Verified-User-Data"

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


def _filter_headers(headers):
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP}


async def healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def proxy_handler(request: web.Request) -> web.StreamResponse:
    if not request.headers.get(VERIFIED_HEADER):
        return web.Response(status=403, text="Missing verified user data")

    path = request.match_info.get("path", "")
    target = f"{UPSTREAM}/{path}"
    if request.query_string:
        target = f"{target}?{request.query_string}"

    # WebSocket upgrade
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await _proxy_websocket(request, target)

    return await _proxy_http(request, target)


async def _proxy_http(request: web.Request, target: str) -> web.Response:
    headers = _filter_headers(request.headers)
    async with ClientSession() as session:
        async with session.request(
            method=request.method,
            url=target,
            headers=headers,
            data=await request.read(),
            allow_redirects=False,
        ) as resp:
            body = await resp.read()
            response_headers = _filter_headers(resp.headers)
            return web.Response(status=resp.status, body=body, headers=response_headers)


async def _proxy_websocket(request: web.Request, target: str) -> web.WebSocketResponse:
    protocols = request.headers.getall("Sec-WebSocket-Protocol", [])
    # Flatten comma-separated protocols into individual items
    all_protocols = []
    for p in protocols:
        all_protocols.extend(s.strip() for s in p.split(",") if s.strip())

    ws_client = web.WebSocketResponse(protocols=tuple(all_protocols))
    await ws_client.prepare(request)

    ws_target = target.replace("http://", "ws://", 1).replace("https://", "wss://", 1)

    async with ClientSession() as session:
        async with session.ws_connect(ws_target, protocols=tuple(all_protocols)) as ws_upstream:

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

            import asyncio

            await asyncio.gather(
                forward_client_to_upstream(),
                forward_upstream_to_client(),
                return_exceptions=True,
            )

    return ws_client


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/healthz", healthz)
    app.router.add_route("*", "/{path:.*}", proxy_handler)
    return app


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else LISTEN_PORT
    web.run_app(create_app(), host="0.0.0.0", port=port)
