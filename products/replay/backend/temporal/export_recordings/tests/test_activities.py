import json
import hashlib
import contextlib
import dataclasses
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync, sync_to_async
from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.recordings.errors import BlockFetchError, BlockNotFoundError, RecordingDeletedError

from products.replay.backend.temporal.export_recordings import activities
from products.replay.backend.temporal.export_recordings.activities import (
    CustomerBucket,
    export_shard,
    list_shard_sessions,
    load_session_metadata,
    policy_statements,
)
from products.replay.backend.temporal.export_recordings.quote import measure_usage
from products.replay.backend.temporal.export_recordings.types import ExportDestination, ExportShardInput, ExportTotals

ACTIVITIES = "products.replay.backend.temporal.export_recordings.activities"
EXPECTED_BLOCKS = b"\x00\x00\x00\x0abb:100-149" + b"\x00\x00\x00\x06aa:0-9"
BUCKET_OWNER = "123456789012"


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploads: dict[str, list[bytes]] = {}
        self.request_args: dict[str, dict[str, str]] = {}

    async def put_object(self, *, Bucket: str, Key: str, Body: bytes, **args: str) -> None:
        self.objects[f"{Bucket}/{Key}"] = bytes(Body)
        self.request_args[f"{Bucket}/{Key}"] = args

    async def create_multipart_upload(self, *, Bucket: str, Key: str, **args: str) -> dict[str, str]:
        self.uploads[f"{Bucket}/{Key}"] = []
        self.request_args[f"{Bucket}/{Key}"] = args
        return {"UploadId": f"{Bucket}/{Key}"}

    async def upload_part(self, *, UploadId: str, Body: bytes, **_: Any) -> dict[str, str]:
        self.uploads[UploadId].append(bytes(Body))
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
        self.file_key = f"customer/exports/{self.team.pk}/run-1/{self.day.date().isoformat()}/s1.phrec"

    def _run(
        self, heartbeat_details: list[Any] | None = None, s1_fetch_errors: Sequence[Exception] | None = None
    ) -> ExportTotals:
        errors = list(s1_fetch_errors or [])

        async def fetch_block(key: str, start: int, end: int, session_id: str, *_: Any, **__: Any) -> bytes:
            if session_id == "s2":
                raise RecordingDeletedError("deleted")
            if session_id == "s1" and errors:
                raise errors.pop(0)
            return f"{key[-2:]}:{start}-{end}".encode()

        recordings = MagicMock()
        recordings.fetch_block = fetch_block

        @contextlib.asynccontextmanager
        async def recording_api(**_: Any) -> AsyncIterator[MagicMock]:
            yield recordings

        @contextlib.asynccontextmanager
        async def bucket(*_: Any) -> AsyncIterator[CustomerBucket]:
            yield CustomerBucket(self.s3, self.destination, BUCKET_OWNER)  # type: ignore[arg-type]

        env = ActivityEnvironment()
        if heartbeat_details:
            env.info = dataclasses.replace(env.info, heartbeat_details=heartbeat_details)
        with (
            patch(f"{ACTIVITIES}.recording_api_client", recording_api),
            patch(f"{ACTIVITIES}.customer_bucket", bucket),
            patch.object(activities, "BLOCK_RETRY_DELAY_SECONDS", 0),
            # A pool thread has its own connection and cannot see this test's uncommitted rows.
            patch(f"{ACTIVITIES}.database_sync_to_async_pool", sync_to_async),
        ):
            return async_to_sync(self._run_activity)(env, self._shard_input())

    def _shard_input(self, day: datetime | None = None) -> ExportShardInput:
        return ExportShardInput(
            team_id=self.team.pk,
            destination=self.destination,
            run_id="run-1",
            day=(day or self.day).date().isoformat(),
            shard=0,
            shards_per_day=1,
            session_ids_key=None,
            quoted_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
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
        body = self.s3.objects[self.file_key]
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

    @parameterized.expand(
        [
            ("bucket_default_encryption", None, {}),
            ("kms_key", "key-1", {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": "key-1"}),
        ]
    )
    def test_uses_multipart_upload_for_large_sessions(
        self, _: str, kms_key_id: str | None, expected_encryption: dict[str, str]
    ) -> None:
        self.destination = dataclasses.replace(self.destination, kms_key_id=kms_key_id)
        with patch.object(activities, "UPLOAD_PART_BYTES", 64):
            self._run()

        body = self.s3.objects[self.file_key]
        assert body.endswith(EXPECTED_BLOCKS)
        assert self._manifest()[0]["sha256"] == hashlib.sha256(body).hexdigest()
        manifest_key = next(key for key in self.s3.objects if "/manifests/" in key)
        # The session file goes through a multipart upload and the manifest through a single PUT.
        expected_args = {"ExpectedBucketOwner": BUCKET_OWNER, **expected_encryption}
        assert self.s3.request_args[self.file_key] == self.s3.request_args[manifest_key] == expected_args

    @parameterized.expand(
        [
            ("not_found_marks_missing", [BlockNotFoundError("Block not found")], "missing"),
            ("timeout_is_retried", [TimeoutError()], "exported"),
        ]
    )
    def test_block_fetch_errors(self, _: str, errors: list[Exception], expected_status: str) -> None:
        self._run(s1_fetch_errors=errors)

        assert [(m["session_id"], m["status"]) for m in self._manifest()] == [
            ("s1", expected_status),
            ("s2", "deleted"),
        ]

    def test_transient_block_errors_fail_the_shard_instead_of_marking_sessions_missing(self) -> None:
        with self.assertRaises(BlockFetchError):
            self._run(
                s1_fetch_errors=[BlockFetchError("Failed to fetch block")]
                * activities.BLOCK_FETCH_ATTEMPTS
                * len(self.blocks["s1"])
            )

        assert self._manifest() == []
        assert self.s3.uploads == {}

    def test_session_crossing_midnight_is_listed_on_its_start_day_with_every_block(self) -> None:
        midnight = (self.day + timedelta(days=1)).replace(hour=0)
        old_file_ms = int((datetime.now(UTC) - timedelta(days=60)).timestamp() * 1000)
        for offset, suffix in ((-timedelta(minutes=1), "f1"), (timedelta(minutes=1), "f2")):
            produce_replay_summary(
                team_id=self.team.pk,
                session_id="s5",
                distinct_id="d-s5",
                first_timestamp=midnight + offset,
                last_timestamp=midnight + offset + timedelta(seconds=30),
                block_urls=[
                    f"s3://replay-bucket/session_recordings/30d/{old_file_ms}-00000000000000{suffix}?range=bytes=0-9"
                ],
                block_first_timestamps=[midnight + offset],
                block_last_timestamps=[midnight + offset + timedelta(seconds=30)],
                ensure_analytics_event_in_session=False,
            )

        def listed(day: datetime) -> dict[str, int]:
            return {s.session_id: len(s.blocks or []) for s in list_shard_sessions(self._shard_input(day))}

        assert listed(self.day)["s5"] == 2
        assert "s5" not in listed(midnight)
        next_day = midnight.date().isoformat()
        assert measure_usage(self.team.pk, next_day, next_day, None, datetime.now(UTC)).sessions == 1

    def test_viewport_batches_that_hit_the_row_limit_are_split(self) -> None:
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d-s2",
            timestamp=self.day + timedelta(seconds=5),
            properties={"$session_id": "s2", "$viewport_width": 800, "$viewport_height": 600},
        )
        flush_persons_and_events()
        sessions = [s for s in list_shard_sessions(self._shard_input()) if s.session_id in ("s1", "s2")]

        with patch.object(activities, "VIEWPORT_ROW_LIMIT", 1):
            viewports, _ = load_session_metadata(self.team.pk, sessions)

        assert {session_id: len(rows) for session_id, rows in viewports.items()} == {"s1": 1, "s2": 1}

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


ROLE_ARN = "arn:aws:iam::123456789012:role/replay-export"


@pytest.mark.parametrize(
    "kms_key_id,expected_kms_resource",
    [
        (None, None),
        ("key-1", "arn:aws:kms:us-east-1:123456789012:key/key-1"),
        ("arn:aws:kms:eu-west-1:210987654321:key/key-2", "arn:aws:kms:eu-west-1:210987654321:key/key-2"),
    ],
)
def test_policy_allows_the_kms_key_only_when_one_is_set(
    kms_key_id: str | None, expected_kms_resource: str | None
) -> None:
    destination = ExportDestination(
        integration_id=1, bucket="customer", region="us-east-1", prefix="exports", kms_key_id=kms_key_id
    )

    statements = policy_statements(destination, 7, ROLE_ARN)

    assert statements[0]["Resource"] == "arn:aws:s3:::customer/exports/7/*"
    assert [s["Resource"] for s in statements[1:]] == ([expected_kms_resource] if expected_kms_resource else [])
