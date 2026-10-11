import time

import unittest
from unittest.mock import patch

import jwt
from aiohttp import ClientWebSocketResponse, WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer
from parameterized import parameterized
from relay import AUDIENCE, Budget, Relay, Tokens

KEY = "test-only-signing-key-never-use-in-production"
ORIGIN = "https://app.example.com"


class TestTokens(unittest.TestCase):
    @parameterized.expand([("expired", -1, AUDIENCE), ("too_long", 7201, AUDIENCE), ("wrong_audience", 60, "other")])
    def test_rejects_invalid_access(self, _name: str, ttl: int, audience: str) -> None:
        now = int(time.time())
        token = jwt.encode({"aud": audience, "scope": "group", "iat": now, "exp": now + ttl}, KEY, algorithm="HS256")
        with self.assertRaises(ValueError):
            Tokens([KEY]).verify(token)

    def test_rotation_and_bandwidth_limit(self) -> None:
        tokens = Tokens(["new-test-only-signing-key-32-characters", KEY])
        self.assertEqual(tokens.verify(Tokens([KEY]).mint("group", 60)).scope, "group")
        budget = Budget(0, 1501)
        self.assertTrue(budget.consume(1501))
        self.assertFalse(budget.consume(1))


class TestRelay(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tokens = Tokens([KEY])
        self.relay = Relay(self.tokens, {ORIGIN})
        self.client = TestClient(TestServer(self.relay.application()))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def connect(self, action: str, room: str = "", scope: str = "group") -> ClientWebSocketResponse:
        socket = await self.client.ws_connect("/netplay", origin=ORIGIN)
        await socket.send_json({"action": action, "room": room, "token": self.tokens.mint(scope, 60)})
        return socket

    async def test_host_and_two_players_exchange_only_addressed_packets(self) -> None:
        host = await self.connect("host")
        room = (await host.receive_json())["room"]
        first = await self.connect("join", room)
        second = await self.connect("join", room)
        self.assertEqual((await first.receive_json())["type"], "joined")
        self.assertEqual((await second.receive_json())["type"], "joined")
        await first.send_bytes(bytes([0, 192, 219, 1]))
        self.assertEqual((await host.receive(timeout=2)).data, bytes([1, 192, 219, 1]))
        await second.send_bytes(bytes([0, 2]))
        self.assertEqual((await host.receive(timeout=2)).data, bytes([2, 2]))
        await host.send_bytes(bytes([2, 3]))
        self.assertEqual((await second.receive(timeout=2)).data, bytes([0, 3]))
        await host.close()
        self.assertEqual((await first.receive(timeout=2)).type, WSMsgType.CLOSE)
        self.assertEqual((await second.receive(timeout=2)).type, WSMsgType.CLOSE)
        self.assertFalse(self.relay.rooms)

    async def test_rejects_unauthorized_origins_tokens_and_other_groups(self) -> None:
        with self.assertRaises(WSServerHandshakeError):
            await self.client.ws_connect("/netplay", origin="https://untrusted.example.com")
        unauthorized = await self.client.ws_connect("/netplay", origin=ORIGIN)
        await unauthorized.send_json({"action": "host", "token": "invalid-test-token"})
        self.assertEqual((await unauthorized.receive(timeout=2)).data, 1008)
        self.assertFalse(self.relay.rooms)
        host = await self.connect("host")
        room = (await host.receive_json())["room"]
        outsider = await self.connect("join", room, scope="other-group")
        self.assertEqual((await outsider.receive(timeout=2)).data, 1008)
        self.assertEqual(len(self.relay.rooms), 1)

    async def test_rejects_peer_spoofing_and_oversized_packets(self) -> None:
        host = await self.connect("host")
        room = (await host.receive_json())["room"]
        player = await self.connect("join", room)
        await player.receive_json()
        await player.send_bytes(bytes([2, 123]))
        self.assertEqual((await player.receive(timeout=2)).data, 1008)
        player = await self.connect("join", room)
        await player.receive_json()
        await player.send_bytes(bytes(1502))
        self.assertEqual((await player.receive(timeout=2)).data, 1008)
        self.assertFalse(host.closed)

    async def test_game_launch_closes_lobby_but_keeps_existing_players(self) -> None:
        host = await self.connect("host")
        room = (await host.receive_json())["room"]
        player = await self.connect("join", room)
        await player.receive_json()
        await host.send_str("launched")
        # A packet on the same connection confirms the launch was processed before joining.
        await host.send_bytes(bytes([1, 1]))
        await player.receive(timeout=2)
        late = await self.connect("join", room)
        self.assertEqual((await late.receive(timeout=2)).data, 1008)
        await player.send_bytes(bytes([0, 2]))
        self.assertEqual((await host.receive(timeout=2)).data, bytes([1, 2]))

    async def test_scope_room_and_player_limits(self) -> None:
        host = await self.connect("host")
        room = (await host.receive_json())["room"]
        for _ in range(3):
            player = await self.connect("join", room)
            await player.receive_json()
        extra = await self.connect("join", room)
        self.assertEqual((await extra.receive(timeout=2)).data, 1008)
        second = await self.connect("host")
        await second.receive_json()
        excess = await self.connect("host")
        self.assertEqual((await excess.receive(timeout=2)).data, 1008)

    async def test_access_expiry_ends_an_active_connection(self) -> None:
        token = self.tokens.mint("group", 60)
        socket = await self.client.ws_connect("/netplay", origin=ORIGIN)
        with patch("relay.time.time", return_value=time.time() + 120):
            await socket.send_json({"action": "host", "token": token})
            self.assertEqual((await socket.receive_json())["type"], "room")
            self.assertEqual((await socket.receive(timeout=2)).data, 1008)


if __name__ == "__main__":
    unittest.main()
