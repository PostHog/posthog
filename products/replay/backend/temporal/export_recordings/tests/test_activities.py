import json
import asyncio
import hashlib
import contextlib
import dataclasses
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync, sync_to_async
from botocore.exceptions import ClientError
from parameterized import parameterized
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.models.integration.common import IntegrationError
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.recordings.errors import BlockFetchError, BlockNotFoundError, RecordingDeletedError
from posthog.storage import object_storage
from posthog.test.persons import create_person

from products.replay.backend.temporal.export_recordings import activities
from products.replay.backend.temporal.export_recordings.activities import (
    Block,
    ByteBudget,
    CustomerBucket,
    SessionRow,
    ViewportReader,
    check_destination,
    destination_error,
    export_session,
    export_shard,
    fetch_blocks_in_order,
    list_shard_sessions,
    load_day_viewports,
    load_shard_session_ids,
    policy_statements,
    quote_storage_key,
    write_summary,
)
from products.replay.backend.temporal.export_recordings.quote import (
    Quote,
    SelectionError,
    create_quote,
    playlist_session_ids,
    select_sessions,
)
from products.replay.backend.temporal.export_recordings.types import (
    CheckDestinationInput,
    DayViewportsInput,
    ExportDestination,
    ExportShardInput,
    ExportTotals,
    WriteSummaryInput,
)


def _list(input: ExportShardInput) -> list[SessionRow]:
    return list_shard_sessions(input, load_shard_session_ids(input.session_ids_prefix, input.day, input.shard))


ACTIVITIES = "products.replay.backend.temporal.export_recordings.activities"
ROLE_ARN = "arn:aws:iam::123456789012:role/replay-export"
OUR_ROLE_ARN = "arn:aws:iam::210987654321:role/posthog-external-recording-exports"
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
        create_person(team=self.team, distinct_ids=["d-s1"], properties={"email": "person@example.com"})
        flush_persons_and_events()
        self.destination = ExportDestination(role_arn=ROLE_ARN, bucket="customer", region="us-east-1", prefix="exports")
        self.s3 = FakeS3()
        self.quote = self._quote(None)
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
            async_to_sync(self._load_viewports)(self.quote)
            return async_to_sync(self._run_activity)(env, self._shard_input())

    async def _load_viewports(self, quote: Quote) -> None:
        input = DayViewportsInput(
            team_id=self.team.pk,
            run_id="run-1",
            day=self.day.date().isoformat(),
            shards_per_day=quote.shards_per_day,
            session_ids_prefix=quote.session_ids_prefix,
        )
        await ActivityEnvironment().run(load_day_viewports, input)

    def _shard_input(self, day: datetime | None = None, quote: Quote | None = None, shard: int = 0) -> ExportShardInput:
        return ExportShardInput(
            team_id=self.team.pk,
            destination=self.destination,
            run_id="run-1",
            day=(day or self.day).date().isoformat(),
            shard=shard,
            session_ids_prefix=(quote or self.quote).session_ids_prefix,
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

    def _check_destination(
        self, s3: FakeS3, validation_error: Exception | None = None, assume: AsyncMock | None = None
    ) -> MagicMock:
        validate = MagicMock(side_effect=validation_error)

        @contextlib.asynccontextmanager
        async def s3_client(*_: Any, **__: Any) -> AsyncIterator[FakeS3]:
            yield s3

        async def run_check() -> None:
            check = CheckDestinationInput(team_id=self.team.pk, destination=self.destination, run_id="run-1")
            await ActivityEnvironment().run(check_destination, check)

        with (
            self.settings(RECORDING_EXPORT_S3_EXTERNAL_ROLE_ARN=OUR_ROLE_ARN),
            patch(f"{ACTIVITIES}.validate_aws_role_arn", validate),
            patch(f"{ACTIVITIES}.get_credentials_using_user_aws_role", assume or AsyncMock()),
            patch(f"{ACTIVITIES}.s3_client", s3_client),
        ):
            async_to_sync(run_check)()
        return validate

    def test_a_role_that_fails_validation_is_never_assumed_and_is_retried(self) -> None:
        assume = AsyncMock()

        with pytest.raises(ApplicationError) as raised:
            self._check_destination(FakeS3(), IntegrationError("no external id condition"), assume)

        # validate_aws_role_arn raises the same error for STS outages, so Temporal retries it a few times.
        assert not raised.value.non_retryable
        assume.assert_not_called()

    def test_the_write_check_leaves_nothing_in_the_bucket(self) -> None:
        s3 = FakeS3()

        validate = self._check_destination(s3)

        validate.assert_called_once_with(ROLE_ARN, OUR_ROLE_ARN, f"posthog-{self.organization.id}")
        assert (s3.objects, s3.uploads) == ({}, {})
        assert list(s3.request_args) == [f"customer/exports/{self.team.pk}/run-1/preflight"]

    @parameterized.expand(
        [
            ("create_denied", "create_multipart_upload", None, 403, "AccessDenied", "s3:PutObject on s3://customer/"),
            (
                "part_denied_by_kms",
                "upload_part",
                "key-1",
                403,
                "AccessDenied",
                "kms:Decrypt on arn:aws:kms:us-east-1:",
            ),
            ("no_bucket", "create_multipart_upload", None, 404, "NoSuchBucket", "The bucket refused a test upload"),
            ("unavailable", "create_multipart_upload", None, 503, "ServiceUnavailable", None),
            ("request_timeout", "create_multipart_upload", None, 400, "RequestTimeout", None),
        ]
    )
    def test_a_failed_write_check_names_the_missing_permission_and_retries_only_transient_errors(
        self, _: str, call: str, kms_key_id: str | None, status: int, code: str, missing: str | None
    ) -> None:
        self.destination = dataclasses.replace(self.destination, kms_key_id=kms_key_id)
        s3 = FakeS3()
        response: Any = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}

        with patch.object(s3, call, side_effect=ClientError(response, call)), pytest.raises(Exception) as raised:
            self._check_destination(s3)

        if missing is None:
            assert isinstance(raised.value, ClientError)
        else:
            assert isinstance(raised.value, ApplicationError) and raised.value.non_retryable
            assert missing in str(raised.value)
        assert s3.uploads == {}

    def test_a_failed_abort_keeps_the_part_error(self) -> None:
        self.destination = dataclasses.replace(self.destination, kms_key_id="key-1")
        s3 = FakeS3()
        denied: Any = {"Error": {"Code": "AccessDenied"}, "ResponseMetadata": {"HTTPStatusCode": 403}}

        with (
            patch.object(s3, "upload_part", side_effect=ClientError(denied, "UploadPart")),
            patch.object(s3, "abort_multipart_upload", side_effect=ClientError(denied, "AbortMultipartUpload")),
            pytest.raises(ApplicationError, match="kms:Decrypt"),
        ):
            self._check_destination(s3)

    def test_exports_listed_sessions_with_a_manifest(self) -> None:
        totals = self._run()

        assert totals == ExportTotals(exported=1, deleted=1, bytes=totals.bytes)
        body = self.s3.objects[self.file_key]
        magic, header_line, blocks = body.split(b"\n", 2)
        header = json.loads(header_line)
        assert magic == b"PHREC1"
        assert (header["session_id"], header["block_count"], header["distinct_id"]) == ("s1", 2, "d-s1")
        assert header["person"]["properties"] == {"email": "person@example.com"}
        assert [(v["timestamp"], v["width"], v["height"], v["href"]) for v in header["viewports"]] == [
            (int((self.day + timedelta(seconds=5)).timestamp() * 1000), "1280", "720", "https://example.com/a")
        ]
        # Blocks follow playback order, not the order of block_urls.
        assert blocks == EXPECTED_BLOCKS
        assert [(m["session_id"], m["status"]) for m in self._manifest()] == [("s1", "exported"), ("s2", "deleted")]
        assert self._manifest()[0]["sha256"] == hashlib.sha256(body).hexdigest()
        assert self.s3.uploads == {}

    def test_pages_through_the_shard_one_manifest_part_per_page(self) -> None:
        with patch.object(activities, "SESSIONS_PER_CHECKPOINT", 1):
            self._run()

        parts = sorted(key.rsplit("/", 1)[-1] for key in self.s3.objects if "/manifests/" in key)
        day = self.day.date().isoformat()
        assert parts == [f"{day}-0000-0000.jsonl", f"{day}-0000-0001.jsonl"]
        assert [(m["session_id"], m["status"]) for m in self._manifest()] == [("s1", "exported"), ("s2", "deleted")]

    def _quote(self, session_ids: list[str] | None, shards_per_day: int = 1) -> Quote:
        return create_quote(
            team_id=self.team.pk,
            date_from=self.day.date().isoformat(),
            date_to=(self.day + timedelta(days=1)).date().isoformat(),
            session_ids=session_ids,
            region="us-east-1",
            cross_region=False,
            shards_per_day=shards_per_day,
            max_parallel_shards=1,
            selection="test",
        )

    def _listed_by_day(self, quote: Quote) -> list[list[str]]:
        return [
            [s.session_id for s in _list(self._shard_input(day, quote))]
            for day in (self.day, self.day + timedelta(days=1))
        ]

    def test_session_list_is_split_by_start_day_and_limits_each_shard(self) -> None:
        quote = self._quote(["s4", "s2", "not-in-this-team"])

        assert self._listed_by_day(quote) == [["s2"], ["s4"]]
        assert quote.usage.sessions == 2

    def test_each_quoted_session_is_in_exactly_one_shard(self) -> None:
        quote = self._quote(None, shards_per_day=4)

        listed = [s.session_id for shard in range(4) for s in _list(self._shard_input(quote=quote, shard=shard))]

        assert sorted(listed) == ["s1", "s2"]

    def test_a_lost_shard_list_fails_the_shard_without_retrying(self) -> None:
        with pytest.raises(ApplicationError) as error:
            load_shard_session_ids("gone", self.day.date().isoformat(), 0)

        assert error.value.non_retryable

    def test_saved_filter_selects_its_matches_in_the_quote_range(self) -> None:
        for session_id, start in (
            ("s5", self.day + timedelta(hours=3)),
            ("s7", self.day + timedelta(hours=4)),
            ("s6", self.day + timedelta(days=1)),
        ):
            produce_replay_summary(
                team_id=self.team.pk,
                session_id=session_id,
                distinct_id=f"d-{session_id}",
                first_timestamp=start,
                last_timestamp=start + timedelta(seconds=30),
                all_urls=["https://example.com/checkout"],
                block_urls=["s3://replay-bucket/session_recordings/30d/1-00000000000000ab?range=bytes=0-9"],
                block_first_timestamps=[start],
                block_last_timestamps=[start + timedelta(seconds=30)],
                ensure_analytics_event_in_session=False,
            )
        # The filter's own range ends before the quote's sessions, so it must not apply.
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            type=SessionRecordingPlaylist.PlaylistType.FILTERS,
            filters={
                "date_from": "-1h",
                "filter_group": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "recording",
                                    "key": "visited_page",
                                    "value": "/checkout",
                                    "operator": "icontains",
                                }
                            ],
                        }
                    ],
                },
            },
        )
        with patch("products.replay.backend.temporal.export_recordings.quote.PLAYLIST_PAGE_SIZE", 1):
            session_ids = playlist_session_ids(
                self.team,
                playlist.short_id,
                self.day.date().isoformat(),
                (self.day + timedelta(days=1)).date().isoformat(),
            )

        quote = self._quote(session_ids)

        assert self._listed_by_day(quote) == [["s5", "s7"], ["s6"]]
        with (
            patch("products.replay.backend.temporal.export_recordings.quote.MAX_LISTED_SESSIONS", 1),
            pytest.raises(SelectionError),
        ):
            playlist_session_ids(self.team, playlist.short_id, quote.date_from, quote.date_to)

    @parameterized.expand([("complete_run", True, 0), ("run_with_skipped_shards", False, None)])
    def test_summary_keeps_our_cost_out_of_the_customer_bucket(
        self, _: str, complete: bool, expected_deleted_before_run: int | None
    ) -> None:
        quote = {"date_from": "2026-01-01", "date_to": "2026-01-02", "usage": {"sessions": 3}, "cost": {"total_usd": 1}}
        object_storage.write(quote_storage_key(f"q-{self.team.pk}"), json.dumps(quote))
        input = WriteSummaryInput(
            team_id=self.team.pk,
            destination=self.destination,
            quote_id=f"q-{self.team.pk}",
            run_id="run-1",
            shards_per_day=1,
            started_at="2026-01-03T00:00:00+00:00",
            totals=ExportTotals(exported=2, missing=1),
            failed_shards=(),
            complete=complete,
        )

        @contextlib.asynccontextmanager
        async def bucket(*_: Any) -> AsyncIterator[CustomerBucket]:
            yield CustomerBucket(self.s3, self.destination, BUCKET_OWNER)  # type: ignore[arg-type]

        with (
            patch(f"{ACTIVITIES}.customer_bucket", bucket),
            patch(f"{ACTIVITIES}.database_sync_to_async_pool", sync_to_async),
        ):
            async_to_sync(self._run_summary)(input)

        prefix = f"customer/exports/{self.team.pk}/run-1/manifests"
        assert "cost" not in json.loads(self.s3.objects[f"{prefix}/quote.json"])
        summary = json.loads(self.s3.objects[f"{prefix}/summary.json"])
        assert summary["sessions"]["deleted_before_run"] == expected_deleted_before_run

    async def _run_summary(self, input: WriteSummaryInput) -> None:
        await ActivityEnvironment().run(write_summary, input)

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

        quote = self._quote(None)

        def listed(day: datetime) -> dict[str, int]:
            return {s.session_id: len(s.blocks or []) for s in _list(self._shard_input(day, quote))}

        assert listed(self.day)["s5"] == 2
        assert "s5" not in listed(midnight)
        next_day = midnight.date().isoformat()
        assert (
            select_sessions(self.team.pk, next_day, next_day, None, 1, datetime.now(UTC), lambda *_: None).sessions == 1
        )

    @parameterized.expand([("filtered_in_the_query", 10_000), ("filtered_after_the_query", 0)])
    def test_day_viewports_go_to_each_listed_sessions_shard(self, _name: str, max_filtered_sessions: int) -> None:
        for event, session_id, width in (
            ("$screen", "s2", 800),
            ("$autocapture", "s1", 1),
            ("$pageview", "s9", 1),
            ("$pageview", "s1", "wide"),
            ("$pageview", "x" * 140_000, 1),
        ):
            _create_event(
                team=self.team,
                event=event,
                distinct_id=f"d-{session_id}",
                timestamp=self.day + timedelta(seconds=5),
                properties={"$session_id": session_id, "$viewport_width": width, "$viewport_height": 600},
            )
        flush_persons_and_events()
        quote = self._quote(None, shards_per_day=4)

        with (
            patch(f"{ACTIVITIES}.database_sync_to_async_pool", sync_to_async),
            patch.object(activities, "MAX_FILTERED_SESSIONS", max_filtered_sessions),
        ):
            async_to_sync(self._load_viewports)(quote)

        day = self.day.date().isoformat()
        by_shard = {}
        for shard in range(4):
            listed = {s.session_id for s in _list(self._shard_input(quote=quote, shard=shard))}
            viewports = ViewportReader.load(self.team.pk, "run-1", day, shard).take("", "~")
            assert set(viewports) <= listed
            by_shard.update({session_id: [v["width"] for v in rows] for session_id, rows in viewports.items()})
        # s1's autocapture and non-numeric width are dropped, s9 is not in the quote, and an overlong session ID
        # would otherwise break the line-by-line read.
        assert by_shard == {"s1": ["1280"], "s2": ["800"]}

    def test_quote_usage_counts_stored_bytes_and_glacier_blocks(self) -> None:
        day = self.day.date().isoformat()

        usage = select_sessions(self.team.pk, day, day, None, 1, datetime.now(UTC), lambda *_: None)

        # s1 and s2 count. s3 is deleted and s4 started the next day. Only the 90d block is in Glacier IR.
        assert (usage.sessions, usage.blocks, usage.bytes, usage.glacier_blocks, usage.glacier_bytes) == (
            2,
            3,
            10 + 50 + 20,
            1,
            50,
        )

    def test_the_run_lists_the_quoted_sessions_still_present(self) -> None:
        # s1 is deleted and s6 arrives after the quote.
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s1",
            first_timestamp=self.day,
            last_timestamp=self.day + timedelta(seconds=30),
            is_deleted=True,
            ensure_analytics_event_in_session=False,
        )
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s6",
            distinct_id="d-s6",
            first_timestamp=self.day + timedelta(hours=1),
            last_timestamp=self.day + timedelta(hours=1, seconds=30),
            block_urls=["s3://replay-bucket/session_recordings/30d/1-00000000000000ff?range=bytes=0-9"],
            block_first_timestamps=[self.day + timedelta(hours=1)],
            block_last_timestamps=[self.day + timedelta(hours=1, seconds=30)],
            ensure_analytics_event_in_session=False,
        )

        assert [s.session_id for s in _list(self._shard_input())] == ["s2"]
        # A page whose sessions were all deleted does not end the shard.
        with patch.object(activities, "SESSIONS_PER_CHECKPOINT", 1):
            assert [s.session_id for s in _list(self._shard_input())] == ["s2"]


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
        role_arn=ROLE_ARN, bucket="customer", region="us-east-1", prefix="exports", kms_key_id=kms_key_id
    )

    statements = policy_statements(destination, 7, "run-1")

    assert statements[0]["Resource"] == "arn:aws:s3:::customer/exports/7/run-1/*"
    assert [s["Resource"] for s in statements[1:]] == ([expected_kms_resource] if expected_kms_resource else [])


@pytest.mark.parametrize(
    "role_arn,bucket,prefix,kms_key_id,error",
    [
        (ROLE_ARN, "customer", "exports", None, None),
        (ROLE_ARN, "customer", "exports", "arn:aws:kms:us-east-1:123456789012:key/abc-123", None),
        ("replay-export", "customer", "exports", None, "role ARN"),
        (ROLE_ARN, "*", "exports", None, "bucket name"),
        (ROLE_ARN, "customer", "ex*", None, "prefix"),
        (ROLE_ARN, "customer", "exports", "*", "KMS key"),
        (ROLE_ARN, "customer", "exports", "alias/replay", "KMS key"),
    ],
)
def test_destination_rejects_values_that_widen_the_session_policy(
    role_arn: str, bucket: str, prefix: str, kms_key_id: str | None, error: str | None
) -> None:
    destination = ExportDestination(
        role_arn=role_arn, bucket=bucket, region="us-east-1", prefix=prefix, kms_key_id=kms_key_id
    )

    message = destination_error(destination)

    assert (message is None) if error is None else (error in (message or ""))


@pytest.mark.asyncio
async def test_a_session_that_expires_while_the_shard_runs_is_not_exported() -> None:
    now = datetime.now(UTC)
    session = SessionRow(
        session_id="s1",
        distinct_id="d1",
        start_time=now - timedelta(days=31),
        end_time=now - timedelta(days=31),
        blocks=[],
        expiry_time=now - timedelta(minutes=1),
    )
    input = ExportShardInput(
        team_id=1,
        destination=ExportDestination(role_arn=ROLE_ARN, bucket="customer", region="us-east-1", prefix="exports"),
        run_id="run-1",
        day="2026-01-01",
        shard=0,
        session_ids_prefix="unused",
    )

    line = await export_session(MagicMock(), MagicMock(), ByteBudget(1), input, session, [], None)

    assert line.status == "expired"


@pytest.mark.asyncio
async def test_block_fetches_wait_for_the_shard_byte_budget() -> None:
    now = datetime.now(UTC)
    blocks = [Block(key=f"k{i}", start_byte=0, end_byte=99) for i in range(4)]
    sessions = [
        SessionRow(
            session_id=f"s{n}",
            distinct_id="d",
            start_time=now,
            end_time=now,
            blocks=blocks,
            expiry_time=now + timedelta(days=1),
        )
        for n in range(2)
    ]
    in_flight = 0
    peak = 0

    async def fetch(*_: Any, **__: Any) -> bytes:
        nonlocal in_flight, peak
        # A block counts from its fetch until the consumer has written it.
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)
        return b"x" * 100

    client = MagicMock()
    client.fetch_block = fetch
    # Room for 3 blocks of 100 bytes across both sessions.
    budget = ByteBudget(300)

    async def drain(session: SessionRow) -> int:
        nonlocal in_flight
        count = 0
        async for _ in fetch_blocks_in_order(client, session, 1, budget):
            # A slow write: the block stays in memory while other sessions run.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            in_flight -= 1
            count += 1
        return count

    assert await asyncio.gather(*(drain(s) for s in sessions)) == [4, 4]
    assert peak <= 3
    assert budget.used == 0
