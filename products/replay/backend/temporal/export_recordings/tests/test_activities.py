import json
import hashlib
import contextlib
import dataclasses
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync
from temporalio.testing import ActivityEnvironment

from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.recordings.errors import RecordingDeletedError

from products.replay.backend.temporal.export_recordings import activities
from products.replay.backend.temporal.export_recordings.activities import export_shard
from products.replay.backend.temporal.export_recordings.quote import measure_usage
from products.replay.backend.temporal.export_recordings.types import ExportDestination, ExportShardInput, ExportTotals

ACTIVITIES = "products.replay.backend.temporal.export_recordings.activities"
EXPECTED_BLOCKS = b"\x00\x00\x00\x0abb:100-149" + b"\x00\x00\x00\x06aa:0-9"


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploads: dict[str, list[bytes]] = {}

    async def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self.objects[f"{Bucket}/{Key}"] = Body

    async def create_multipart_upload(self, *, Bucket: str, Key: str) -> dict[str, str]:
        self.uploads[f"{Bucket}/{Key}"] = []
        return {"UploadId": f"{Bucket}/{Key}"}

    async def upload_part(self, *, UploadId: str, Body: bytes, **_: Any) -> dict[str, str]:
        self.uploads[UploadId].append(Body)
        return {"ETag": str(len(self.uploads[UploadId]))}

    async def complete_multipart_upload(self, *, UploadId: str, **_: Any) -> None:
        self.objects[UploadId] = b"".join(self.uploads.pop(UploadId))

    async def abort_multipart_upload(self, *, UploadId: str, **_: Any) -> None:
        self.uploads.pop(UploadId)


class TestExportRecordings(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.day = (datetime.now(UTC) - timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)
        old_file_ms = int((datetime.now(UTC) - timedelta(days=60)).timestamp() * 1000)
        self.blocks = {
            "s1": [
                (f"session_recordings/30d/{old_file_ms}-00000000000000aa", 0, 9, self.day + timedelta(minutes=1)),
                (f"session_recordings/90d/{old_file_ms}-00000000000000bb", 100, 149, self.day),
            ],
            "s2": [(f"session_recordings/30d/{old_file_ms}-00000000000000cc", 0, 19, self.day)],
            "s3": [(f"session_recordings/30d/{old_file_ms}-00000000000000dd", 0, 9, self.day)],
            "s4": [(f"session_recordings/30d/{old_file_ms}-00000000000000ee", 0, 9, self.day + timedelta(days=1))],
        }
        for session_id, blocks in self.blocks.items():
            produce_replay_summary(
                team_id=self.team.pk,
                session_id=session_id,
                distinct_id=f"d-{session_id}",
                first_timestamp=blocks[-1][3] if session_id == "s1" else blocks[0][3],
                last_timestamp=max(b[3] for b in blocks) + timedelta(seconds=30),
                block_urls=[f"s3://replay-bucket/{key}?range=bytes={start}-{end}" for key, start, end, _ in blocks],
                block_first_timestamps=[b[3] for b in blocks],
                block_last_timestamps=[b[3] + timedelta(seconds=30) for b in blocks],
                is_deleted=session_id == "s3",
                ensure_analytics_event_in_session=False,
            )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d-s1",
            timestamp=self.day + timedelta(seconds=5),
            properties={
                "$session_id": "s1",
                "$viewport_width": 1280,
                "$viewport_height": 720,
                "$current_url": "https://example.com/a",
            },
        )
        flush_persons_and_events()
        self.destination = ExportDestination(integration_id=1, bucket="customer", region="us-east-1", prefix="exports")
        self.s3 = FakeS3()

    def _run(self, heartbeat_details: list[Any] | None = None) -> ExportTotals:
        async def fetch_block(key: str, start: int, end: int, session_id: str, *_: Any, **__: Any) -> bytes:
            if session_id == "s2":
                raise RecordingDeletedError("deleted")
            return f"{key[-2:]}:{start}-{end}".encode()

        recordings = MagicMock()
        recordings.fetch_block = fetch_block

        @contextlib.asynccontextmanager
        async def recording_api(**_: Any) -> AsyncIterator[MagicMock]:
            yield recordings

        @contextlib.asynccontextmanager
        async def destination(*_: Any) -> AsyncIterator[FakeS3]:
            yield self.s3

        env = ActivityEnvironment()
        if heartbeat_details:
            env.info = dataclasses.replace(env.info, heartbeat_details=heartbeat_details)
        with (
            patch(f"{ACTIVITIES}.recording_api_client", recording_api),
            patch(f"{ACTIVITIES}.destination_client", destination),
        ):
            return async_to_sync(self._run_activity)(
                env,
                ExportShardInput(
                    team_id=self.team.pk,
                    destination=self.destination,
                    run_id="run-1",
                    day=self.day.date().isoformat(),
                    shard=0,
                    shards_per_day=1,
                    session_ids_key=None,
                    quoted_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
                ),
            )

    async def _run_activity(self, env: ActivityEnvironment, input: ExportShardInput) -> ExportTotals:
        return await env.run(export_shard, input)

    def _manifest(self) -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for key, body in sorted(self.s3.objects.items())
            if "/manifests/" in key
            for line in body.decode().splitlines()
        ]

    def test_exports_listed_sessions_with_a_manifest(self) -> None:
        totals = self._run()

        assert totals == ExportTotals(exported=1, deleted=1, bytes=totals.bytes)
        file_key = f"customer/exports/{self.team.pk}/{self.day.date().isoformat()}/s1.phrec"
        body = self.s3.objects[file_key]
        magic, header_line, blocks = body.split(b"\n", 2)
        header = json.loads(header_line)
        assert magic == b"PHREC1"
        assert (header["session_id"], header["block_count"], header["distinct_id"]) == ("s1", 2, "d-s1")
        assert [(v["width"], v["height"], v["href"]) for v in header["viewports"]] == [
            ("1280", "720", "https://example.com/a")
        ]
        # Blocks follow playback order, not the order of block_urls.
        assert blocks == EXPECTED_BLOCKS
        assert [(m["session_id"], m["status"]) for m in self._manifest()] == [("s1", "exported"), ("s2", "deleted")]
        assert self._manifest()[0]["sha256"] == hashlib.sha256(body).hexdigest()
        assert self.s3.uploads == {}

    def test_resumes_after_the_last_checkpointed_session(self) -> None:
        checkpoint = {"last_session_id": "s1", "manifest_parts": 1, "totals": dataclasses.asdict(ExportTotals())}

        self._run(heartbeat_details=[checkpoint])

        assert [key.rsplit("/", 1)[-1] for key in self.s3.objects] == [f"{self.day.date().isoformat()}-0000-0001.jsonl"]
        assert [(m["session_id"], m["status"]) for m in self._manifest()] == [("s2", "deleted")]

    def test_uses_multipart_upload_for_large_sessions(self) -> None:
        with patch.object(activities, "UPLOAD_PART_BYTES", 64):
            self._run()

        body = self.s3.objects[f"customer/exports/{self.team.pk}/{self.day.date().isoformat()}/s1.phrec"]
        assert body.endswith(EXPECTED_BLOCKS)
        assert self._manifest()[0]["sha256"] == hashlib.sha256(body).hexdigest()

    def test_quote_usage_counts_stored_bytes_and_glacier_blocks(self) -> None:
        day = self.day.date().isoformat()

        usage = measure_usage(self.team.pk, day, day, None, datetime.now(UTC))

        # s1 and s2 count. s3 is deleted and s4 started the next day. Only the 90d block is in Glacier IR.
        assert (usage.sessions, usage.blocks, usage.bytes, usage.glacier_blocks, usage.glacier_bytes) == (
            2,
            3,
            10 + 50 + 20,
            1,
            50,
        )
