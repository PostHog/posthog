import os
import re
import sys
import json
import time
import asyncio
import secrets
import argparse
from dataclasses import dataclass

import jwt
from aiohttp import WSMsgType, web

AUDIENCE = "posthog-terminal-relay"
MAX_TOKEN_SECONDS = 7200
MAX_PACKET_BYTES = 1501
MAX_CONNECTIONS = 128
MAX_ROOMS = 32
MAX_SCOPE_ROOMS = 2
MAX_PLAYERS = 4
ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True)
class Access:
    scope: str
    expires: int


class Tokens:
    def __init__(self, keys: list[str]) -> None:
        if not keys or any(len(key) < 32 for key in keys):
            raise ValueError("RELAY_SIGNING_KEYS must contain independent keys of at least 32 characters")
        self.keys = keys

    def mint(self, scope: str, ttl: int) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", scope) or not 1 <= ttl <= MAX_TOKEN_SECONDS:
            raise ValueError("Use a scope of 1–64 letters, digits, underscores or hyphens, and a TTL of 1–7200 seconds")
        now = int(time.time())
        return jwt.encode(
            {"aud": AUDIENCE, "scope": scope, "iat": now, "exp": now + ttl}, self.keys[0], algorithm="HS256"
        )

    def verify(self, token: object) -> Access:
        if not isinstance(token, str) or len(token) > 2048:
            raise ValueError("Invalid or expired relay token")
        for key in self.keys:
            try:
                claims = jwt.decode(
                    token,
                    key,
                    algorithms=["HS256"],
                    audience=AUDIENCE,
                    options={"require": ["aud", "scope", "iat", "exp"]},
                )
            except jwt.InvalidTokenError:
                continue
            scope, issued, expires = claims["scope"], claims["iat"], claims["exp"]
            if (
                isinstance(scope, str)
                and re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", scope)
                and type(issued) is int
                and type(expires) is int
                and 0 < expires - issued <= MAX_TOKEN_SECONDS
            ):
                return Access(scope, expires)
        raise ValueError("Invalid or expired relay token")


class Budget:
    def __init__(self, rate: int, burst: int) -> None:
        self.rate = rate
        self.burst = burst
        self.available = float(burst)
        self.updated = time.monotonic()

    def consume(self, amount: int) -> bool:
        now = time.monotonic()
        self.available = min(self.burst, self.available + (now - self.updated) * self.rate)
        self.updated = now
        if amount > self.available:
            return False
        self.available -= amount
        return True


class Room:
    def __init__(self, host: web.WebSocketResponse) -> None:
        self.peers = {0: host}
        self.next_peer = 1
        self.launched = False


@dataclass(frozen=True, kw_only=True)
class Membership:
    access: Access
    code: str
    room: Room
    peer: int


class Relay:
    def __init__(self, tokens: Tokens, origins: set[str]) -> None:
        if not origins or "*" in origins:
            raise ValueError("RELAY_ALLOWED_ORIGINS must list the PostHog origins allowed to connect")
        self.tokens = tokens
        self.origins = origins
        self.rooms: dict[tuple[str, str], Room] = {}
        self.connections: set[web.WebSocketResponse] = set()
        self.cleanup_tasks: set[asyncio.Task[None]] = set()
        self.handshakes = Budget(10, 20)

    def register(self, message: object, socket: web.WebSocketResponse) -> Membership:
        if not isinstance(message, dict):
            raise ValueError("Invalid handshake")
        access = self.tokens.verify(message.get("token"))
        action = message.get("action")
        if action == "host":
            if len(self.rooms) >= MAX_ROOMS or sum(scope == access.scope for scope, _ in self.rooms) >= MAX_SCOPE_ROOMS:
                raise ValueError("Too many rooms. Close an existing game and try again.")
            while (access.scope, code := "".join(secrets.choice(ROOM_ALPHABET) for _ in range(6))) in self.rooms:
                pass
            room = Room(socket)
            self.rooms[access.scope, code] = room
            peer = 0
        elif action == "join":
            requested_room = message.get("room")
            if not isinstance(requested_room, str) or not re.fullmatch(r"[A-Z0-9]{6}", requested_room):
                raise ValueError("Invalid room code")
            code = requested_room
            found = self.rooms.get((access.scope, code))
            if found is None or found.launched or found.peers[0].closed:
                raise ValueError("No open room has this code. Ask the host to start a new game.")
            room = found
            # Never reuse an address: Doom may still associate it with a disconnected player.
            if room.next_peer >= MAX_PLAYERS:
                raise ValueError("This room is full. Ask the host to start a new game.")
            peer = room.next_peer
            room.next_peer += 1
            room.peers[peer] = socket
        else:
            raise ValueError("Invalid handshake")
        return Membership(access=access, code=code, room=room, peer=peer)

    async def forward(self, room: Room, peer: int, payload: bytes) -> None:
        if not 2 <= len(payload) <= MAX_PACKET_BYTES:
            raise ValueError("Invalid game packet")
        destination = payload[0]
        if (peer != 0 and destination != 0) or destination == peer or destination >= MAX_PLAYERS:
            raise ValueError("Invalid game destination")
        target = room.peers.get(destination)
        if target is not None and not target.closed:
            try:
                async with asyncio.timeout(2):
                    await target.send_bytes(bytes([peer]) + payload[1:])
            except (TimeoutError, ConnectionError):
                await target.close(code=1013, message=b"Connection too slow")

    async def close_players(self, room: Room) -> None:
        await asyncio.gather(
            *(
                other.close(code=1001, message=b"The host disconnected")
                for index, other in list(room.peers.items())
                if index != 0
            )
        )

    async def connect(self, request: web.Request) -> web.WebSocketResponse:
        if request.headers.get("Origin") not in self.origins:
            raise web.HTTPForbidden()
        if len(self.connections) >= MAX_CONNECTIONS or not self.handshakes.consume(1):
            raise web.HTTPTooManyRequests()
        socket = web.WebSocketResponse(max_msg_size=4096, heartbeat=20, compress=False, timeout=2, writer_limit=16384)
        self.connections.add(socket)
        room: Room | None = None
        key: tuple[str, str] | None = None
        peer = -1
        try:
            await socket.prepare(request)
            async with asyncio.timeout(5):
                first = await socket.receive()
                if first.type != WSMsgType.TEXT:
                    raise ValueError("Send a relay handshake first")
                membership = self.register(json.loads(first.data), socket)
                room = membership.room
                peer = membership.peer
                key = (membership.access.scope, membership.code)
                await socket.send_json({"type": "room" if peer == 0 else "joined", "room": membership.code})
            packets = Budget(128, 256)
            bandwidth = Budget(65536, 131072)
            async with asyncio.timeout(max(0, membership.access.expires - time.time())):
                async for message in socket:
                    if not packets.consume(1):
                        raise ValueError("Game traffic limit exceeded")
                    if message.type == WSMsgType.BINARY:
                        if not bandwidth.consume(len(message.data)):
                            raise ValueError("Game traffic limit exceeded")
                        await self.forward(room, peer, message.data)
                    elif message.type == WSMsgType.TEXT and peer == 0 and message.data == "launched":
                        room.launched = True
                    else:
                        raise ValueError("Invalid game message")
        except (ValueError, TimeoutError) as error:
            if socket.prepared and not socket.closed:
                # JSON parser errors include user input; only fixed protocol errors leave this service.
                detail = "Invalid handshake" if isinstance(error, json.JSONDecodeError) else str(error)
                await socket.close(code=1008, message=(detail or "Relay access expired or timed out").encode()[:120])
        except ConnectionError:
            pass
        finally:
            self.connections.discard(socket)
            if room is not None and key is not None:
                if peer == 0:
                    self.rooms.pop(key, None)
                    # A host disconnect can cancel its request handler during player cleanup.
                    cleanup = asyncio.create_task(self.close_players(room))
                    self.cleanup_tasks.add(cleanup)
                    cleanup.add_done_callback(self.cleanup_tasks.discard)
                    await asyncio.shield(cleanup)
                else:
                    room.peers.pop(peer, None)
        return socket

    async def shutdown(self, app: web.Application) -> None:
        await asyncio.gather(
            *(socket.close(code=1001, message=b"Relay shutting down") for socket in list(self.connections))
        )
        await asyncio.gather(*list(self.cleanup_tasks))

    def application(self) -> web.Application:
        app = web.Application(client_max_size=4096)
        app.router.add_get("/netplay", self.connect)
        app.on_shutdown.append(self.shutdown)
        return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Relay Doom packets between browser terminals")
    parser.add_argument("command", choices=["serve", "token"])
    parser.add_argument("--scope", default="")
    parser.add_argument("--ttl", type=int, default=3600)
    args = parser.parse_args()
    tokens = Tokens([key.strip() for key in os.environ.get("RELAY_SIGNING_KEYS", "").split(",") if key.strip()])
    if args.command == "token":
        sys.stdout.write(tokens.mint(args.scope, args.ttl) + "\n")
    else:
        origins = {
            origin.strip() for origin in os.environ.get("RELAY_ALLOWED_ORIGINS", "").split(",") if origin.strip()
        }
        relay = Relay(tokens, origins)
        web.run_app(relay.application(), host="0.0.0.0", port=8080, access_log=None)


if __name__ == "__main__":
    main()
