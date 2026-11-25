import os
import json
import tempfile
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import override_settings

import jwt
import snappy
from parameterized import parameterized

STAFF_SECRET = "s" * 32
SESSION_ID = "session-1"
BLOCK_LINES = b'["window-1", {"type": 2}]\n["window-1", {"type": 3}]\n'


class FakeRecordingApi(BaseHTTPRequestHandler):
    listing: dict = {}
    list_status = 200
    busy_replies = 0
    on_list: Callable[[], None] = staticmethod(lambda: None)
    seen_tokens: list[str] = []

    def do_GET(self) -> None:
        self.seen_tokens.append(self.headers["Authorization"].removeprefix("Bearer "))
        prefix = f"/api/projects/{self.server.team_id}/recordings/{SESSION_ID}/blocks"  # type: ignore[attr-defined]
        if FakeRecordingApi.busy_replies:
            FakeRecordingApi.busy_replies -= 1
            self.send_response(503)
            self.send_header("Retry-After", "0")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == prefix:
            FakeRecordingApi.on_list()
            self._reply(self.list_status, json.dumps(self.listing).encode())
        elif self.path == f"{prefix}/ref-0":
            self._reply(200, snappy.compress(BLOCK_LINES))
        else:
            self._reply(404, b'{"error":"Block not found"}')

    def _reply(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


class TestFetchRecordingBlocksCommand(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.out = Path(scratch.name) / "out"
        labels = Path(scratch.name) / "labels"
        labels.write_text('toolbox-claimed="staff_at_example.com"\n')
        labels_path = patch("products.replay.backend.management.commands.recording_api_token.POD_LABELS_PATH", labels)
        labels_path.start()
        self.addCleanup(labels_path.stop)
        # A dead proxy, so the test fails if the command sends its requests through HTTP_PROXY.
        dead_proxy = patch.dict(
            os.environ,
            {"HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "NO_PROXY": "", "no_proxy": ""},
        )
        dead_proxy.start()
        self.addCleanup(dead_proxy.stop)

        FakeRecordingApi.listing = {
            "blocks": [
                {"ref": "ref-0", "start_timestamp": 1, "end_timestamp": 2},
                {"ref": None, "start_timestamp": 3, "end_timestamp": 4},
            ]
        }
        FakeRecordingApi.list_status = 200
        FakeRecordingApi.busy_replies = 0
        FakeRecordingApi.on_list = staticmethod(lambda: None)
        FakeRecordingApi.seen_tokens = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRecordingApi)
        server.team_id = self.team.pk  # type: ignore[attr-defined]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        settings = override_settings(
            RECORDING_API_STAFF_JWT_SECRET=STAFF_SECRET, RECORDING_API_URL=f"http://127.0.0.1:{server.server_port}/"
        )
        settings.enable()
        self.addCleanup(settings.disable)

    def _fetch(self, session_id: str = SESSION_ID) -> dict:
        out = StringIO()
        call_command(
            "fetch_recording_blocks",
            team_id=self.team.pk,
            session_id=session_id,
            reason="ticket 1",
            out=str(self.out),
            stdout=out,
            stderr=StringIO(),
        )
        return json.loads(out.getvalue())

    def test_saves_each_listed_block_decompressed_without_the_egress_proxy(self) -> None:
        FakeRecordingApi.busy_replies = 2

        summary = self._fetch()

        assert summary == {"out": str(self.out), "blocks": 2, "without_ref": 1}
        assert (self.out / "0000.jsonl").read_bytes() == BLOCK_LINES
        assert self.out.stat().st_mode & 0o777 == 0o700
        assert json.loads((self.out / "index.json").read_text()) == [
            {"file": "0000.jsonl", "start_timestamp": 1, "end_timestamp": 2},
            {"file": None, "start_timestamp": 3, "end_timestamp": 4},
        ]
        claims = jwt.decode(
            FakeRecordingApi.seen_tokens[0], STAFF_SECRET, algorithms=["HS256"], audience="posthog:recording_api:staff"
        )
        assert (claims["team_id"], claims["actor"], claims["reason"]) == (
            self.team.pk,
            "staff_at_example.com",
            "ticket 1",
        )

    def test_keeps_writing_into_its_own_directory_when_the_path_is_replaced(self) -> None:
        moved = self.out.with_name("moved")

        def replace_out() -> None:
            self.out.rename(moved)
            self.out.mkdir()

        FakeRecordingApi.on_list = staticmethod(replace_out)

        self._fetch()

        assert list(self.out.iterdir()) == []
        assert (moved / "0000.jsonl").read_bytes() == BLOCK_LINES
        assert (moved / "0000.jsonl").stat().st_mode & 0o777 == 0o600

    @parameterized.expand(
        [
            ("refused_listing", 403, {"blocks": []}, SESSION_ID, "recording-api answered 403"),
            ("empty_listing", 200, {"blocks": []}, SESSION_ID, "lists no blocks"),
            ("no_refs", 200, {"blocks": [{"ref": None}]}, SESSION_ID, "None of the 1 blocks has a ref"),
            ("path_in_session_id", 200, {"blocks": []}, "../../etc", "must not contain a slash"),
        ]
    )
    def test_refuses_when_there_is_nothing_to_save(
        self, _name: str, status: int, listing: dict, session_id: str, error: str
    ) -> None:
        FakeRecordingApi.list_status = status
        FakeRecordingApi.listing = listing

        with self.assertRaisesMessage(CommandError, error):
            self._fetch(session_id)
        assert not self.out.exists()

    @parameterized.expand([("empty", False), ("holding_files", True)])
    def test_refuses_an_output_directory_that_exists(self, _name: str, holds_files: bool) -> None:
        self.out.mkdir()
        if holds_files:
            (self.out / "0007.jsonl").write_text("from an earlier run")

        with self.assertRaisesMessage(CommandError, "already exists"):
            self._fetch()
        assert FakeRecordingApi.seen_tokens == []
