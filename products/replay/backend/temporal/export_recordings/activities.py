import re
import json
import asyncio
import hashlib
import functools
import contextlib
from collections.abc import AsyncIterator, Callable, Coroutine, Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.session_recordings.recordings.errors import BlockFetchError, RecordingDeletedError
from posthog.session_recordings.recordings.recording_api_client import RecordingApiClient, recording_api_client
from posthog.storage import object_storage
from posthog.temporal.common.heartbeat import Heartbeater

from products.batch_exports.backend.facade.contracts import AWSCredentials
from products.batch_exports.backend.facade.destinations.s3 import (
    ExternalRoleArnNotConfiguredError,
    InvalidCredentialsError,
    PolicyStatement,
    S3IntegrationNotFoundError,
    get_credentials_using_user_aws_role,
    get_s3_integration,
    s3_client,
)
from products.replay.backend.temporal.export_recordings.types import (
    ExportDestination,
    ExportShardInput,
    ExportTotals,
    SessionStatus,
    WriteSummaryInput,
)

if TYPE_CHECKING:
    from types_aiobotocore_s3 import S3Client
    from types_aiobotocore_s3.type_defs import CompletedPartTypeDef

logger = structlog.get_logger(__name__)

FILE_MAGIC = b"PHREC1\n"
FILE_VERSION = "2026-11-raw"
FILE_EXTENSION = "phrec"

SESSION_CONCURRENCY = 16
BLOCK_CONCURRENCY = 8
BLOCK_FETCH_ATTEMPTS = 3
RECORDING_API_CONNECTIONS = SESSION_CONCURRENCY * BLOCK_CONCURRENCY
# S3 needs at least 5 MiB for every multipart part except the last.
UPLOAD_PART_BYTES = 16 * 1024 * 1024
SESSIONS_PER_CHECKPOINT = 500
METADATA_BATCH_SIZE = 100

BLOCK_URL_PATTERN = re.compile(r"^s3://[^/]+/(?P<key>[^?]+)\?range=bytes=(?P<start>\d+)-(?P<end>\d+)$")

NON_RETRYABLE_ERRORS = (InvalidCredentialsError, S3IntegrationNotFoundError, ExternalRoleArnNotConfiguredError)

# Rows group by session start, so a day reads the next day too: a session's later rows can start after midnight.
SHARD_SESSIONS_QUERY = """
SELECT
    session_id,
    any(distinct_id),
    min(min_first_timestamp) AS start_time,
    max(max_last_timestamp),
    groupArrayArray(block_first_timestamps),
    groupArrayArray(block_urls),
    dateTrunc('DAY', start_time) + toIntervalDay(coalesce(max(retention_period_days), 30)) AS expiry_time,
    expiry_time < now() AS expired
FROM session_replay_events
PREWHERE team_id = %(team_id)s
    AND min_first_timestamp >= %(day_start)s
    AND min_first_timestamp < %(day_start)s + INTERVAL 2 DAY
WHERE cityHash64(session_id) %% %(shards_per_day)s = %(shard)s
GROUP BY session_id
HAVING max(is_deleted) = 0
    AND start_time >= %(day_start)s
    AND start_time < %(day_start)s + INTERVAL 1 DAY
    AND expiry_time >= %(quoted_at)s
ORDER BY session_id
"""

# A row per viewport state and minute keeps the result small and still follows resizes.
VIEWPORTS_QUERY = """
SELECT
    `$session_id`,
    toUnixTimestamp64Milli(min(timestamp)),
    toString(properties.$viewport_width) AS width,
    toString(properties.$viewport_height) AS height,
    toString(properties.$current_url) AS href
FROM events
WHERE timestamp >= {start} AND timestamp < {end}
    AND `$session_id` IN {session_ids}
    AND isNotNull(properties.$viewport_width) AND isNotNull(properties.$viewport_height)
GROUP BY `$session_id`, width, height, href, toStartOfMinute(timestamp)
ORDER BY `$session_id`, min(timestamp)
LIMIT 50000
"""

PERSONS_QUERY = """
SELECT distinct_id, person.id, person.created_at, person.properties
FROM person_distinct_ids
WHERE distinct_id IN {distinct_ids}
LIMIT 50000
"""


@frozen
class Block:
    key: str
    start_byte: int
    end_byte: int


@frozen
class SessionRow:
    session_id: str
    distinct_id: str
    start_time: datetime
    end_time: datetime
    blocks: list[Block] | None
    expired: bool


@frozen
class ManifestLine:
    session_id: str
    distinct_id: str
    status: SessionStatus
    start_time: str
    end_time: str
    key: str | None = None
    bytes: int = 0
    sha256: str | None = None
    block_count: int = 0

    def to_json(self) -> str:
        return json.dumps(
            {
                "session_id": self.session_id,
                "distinct_id": self.distinct_id,
                "status": self.status,
                "start_time": self.start_time,
                "end_time": self.end_time,
                "key": self.key,
                "bytes": self.bytes,
                "sha256": self.sha256,
                "block_count": self.block_count,
            }
        )


@frozen
class ShardCheckpoint:
    last_session_id: str
    manifest_parts: int
    totals: ExportTotals


def run_prefix(destination: ExportDestination, team_id: int) -> str:
    return f"{destination.prefix.strip('/')}/{team_id}".lstrip("/")


def manifest_prefix(destination: ExportDestination, team_id: int, run_id: str) -> str:
    return f"{run_prefix(destination, team_id)}/manifests/{run_id}"


def session_key(destination: ExportDestination, team_id: int, start_time: datetime, session_id: str) -> str:
    return f"{run_prefix(destination, team_id)}/{start_time:%Y-%m-%d}/{session_id}.{FILE_EXTENSION}"


def quote_storage_key(quote_id: str) -> str:
    return f"session_recording_exports/quotes/{quote_id}.json"


def parse_blocks(block_first_timestamps: list[datetime], block_urls: list[str]) -> list[Block] | None:
    """Return the session's blocks in playback order, or None when a URL does not parse."""
    if len(block_first_timestamps) != len(block_urls):
        return None
    blocks: list[tuple[datetime, Block]] = []
    for first_timestamp, url in zip(block_first_timestamps, block_urls):
        match = BLOCK_URL_PATTERN.match(url)
        if not match:
            return None
        blocks.append(
            (first_timestamp, Block(key=match["key"], start_byte=int(match["start"]), end_byte=int(match["end"])))
        )
    return [block for _, block in sorted(blocks, key=lambda item: item[0])]


def encode_header(header: dict[str, Any]) -> bytes:
    return FILE_MAGIC + json.dumps(header, separators=(",", ":")).encode() + b"\n"


def frame_block(block: bytes) -> bytes:
    return len(block).to_bytes(4, "big") + block


def list_shard_sessions(input: ExportShardInput) -> list[SessionRow]:
    day_start = datetime.fromisoformat(input.day).replace(tzinfo=UTC)
    rows = sync_execute(
        SHARD_SESSIONS_QUERY,
        {
            "team_id": input.team_id,
            "day_start": day_start,
            "shards_per_day": input.shards_per_day,
            "shard": input.shard,
            "quoted_at": datetime.fromisoformat(input.quoted_at),
        },
    )
    allowed = load_session_ids(input.session_ids_key) if input.session_ids_key else None
    return [
        SessionRow(
            session_id=session_id,
            distinct_id=distinct_id,
            start_time=start_time.replace(tzinfo=UTC),
            end_time=end_time.replace(tzinfo=UTC),
            blocks=parse_blocks(first_timestamps, urls),
            expired=bool(expired),
        )
        for session_id, distinct_id, start_time, end_time, first_timestamps, urls, _, expired in rows
        if allowed is None or session_id in allowed
    ]


@functools.cache
def load_session_ids(key: str) -> frozenset[str]:
    content = object_storage.read(key)
    if content is None:
        raise ApplicationError(f"Session ID list {key} does not exist", non_retryable=True)
    return frozenset(line.strip() for line in content.splitlines() if line.strip())


def load_session_metadata(
    team_id: int, sessions: list[SessionRow]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    """Return the viewports per session and the person per distinct ID, which file playback cannot load."""
    team = Team.objects.get(id=team_id)
    viewports: dict[str, list[dict[str, Any]]] = {}
    persons: dict[str, dict[str, Any]] = {}
    for batch_start in range(0, len(sessions), METADATA_BATCH_SIZE):
        batch = sessions[batch_start : batch_start + METADATA_BATCH_SIZE]
        start = min(s.start_time for s in batch) - timedelta(minutes=5)
        end = max(s.end_time for s in batch) + timedelta(minutes=5)
        viewport_rows = execute_hogql_query(
            parse_select(VIEWPORTS_QUERY),
            team,
            placeholders={
                "start": ast.Constant(value=start),
                "end": ast.Constant(value=end),
                "session_ids": ast.Constant(value=[s.session_id for s in batch]),
            },
            limit_context=LimitContext.EXPORT,
        ).results
        for session_id, timestamp, width, height, href in viewport_rows:
            viewports.setdefault(session_id, []).append(
                {"timestamp": timestamp, "width": width, "height": height, "href": href}
            )
        person_rows = execute_hogql_query(
            parse_select(PERSONS_QUERY),
            team,
            placeholders={"distinct_ids": ast.Constant(value=sorted({s.distinct_id for s in batch}))},
            limit_context=LimitContext.EXPORT,
        ).results
        for distinct_id, person_id, created_at, properties in person_rows:
            persons[distinct_id] = {
                "id": person_id,
                "uuid": person_id,
                "distinct_ids": [distinct_id],
                "created_at": created_at.isoformat() if created_at else None,
                "properties": json.loads(properties) if isinstance(properties, str) else properties,
            }
    return viewports, persons


async def resolve_s3_credentials(
    team_id: int, destination: ExportDestination
) -> tuple[AWSCredentials, Callable[[], Coroutine[Any, Any, AWSCredentials]]]:
    integration = await get_s3_integration(destination.integration_id, team_id)
    aws_role_arn: str | None = getattr(integration, "aws_role_arn", None)
    if not aws_role_arn:
        raise ApplicationError("Recording exports need an AWS S3 integration with a role ARN", non_retryable=True)
    team = await Team.objects.aget(id=team_id)
    refresh_using = functools.partial(
        get_credentials_using_user_aws_role,
        aws_role_arn,
        f"posthog-{team.organization_id}",
        session_name=f"PostHog-replay-export-{team_id}",
        policy_statements=[
            PolicyStatement(
                Effect="Allow",
                Action=["s3:PutObject", "s3:AbortMultipartUpload"],
                Resource=f"arn:aws:s3:::{destination.bucket}/{run_prefix(destination, team_id)}/*",
            )
        ],
    )
    return await refresh_using(), refresh_using


@contextlib.asynccontextmanager
async def destination_client(team_id: int, destination: ExportDestination) -> AsyncIterator["S3Client"]:
    try:
        credentials, refresh_using = await resolve_s3_credentials(team_id, destination)
        async with s3_client(credentials, destination.region, refresh_using=refresh_using) as client:
            yield client
    except NON_RETRYABLE_ERRORS as e:
        raise ApplicationError(str(e), non_retryable=True) from e


class SessionUpload:
    """Streams one session file to S3: a single PUT when small, a multipart upload otherwise."""

    def __init__(self, client: "S3Client", bucket: str, key: str) -> None:
        self.client = client
        self.bucket = bucket
        self.key = key
        self.buffer = bytearray()
        self.sha256 = hashlib.sha256()
        self.size = 0
        self.upload_id: str | None = None
        self.parts: list[CompletedPartTypeDef] = []

    async def write(self, data: bytes) -> None:
        self.buffer += data
        self.sha256.update(data)
        self.size += len(data)
        if len(self.buffer) >= UPLOAD_PART_BYTES:
            await self._upload_part()

    async def finish(self) -> None:
        if self.upload_id is None:
            await self.client.put_object(Bucket=self.bucket, Key=self.key, Body=bytes(self.buffer))
            return
        if self.buffer:
            await self._upload_part()
        await self.client.complete_multipart_upload(
            Bucket=self.bucket, Key=self.key, UploadId=self.upload_id, MultipartUpload={"Parts": self.parts}
        )

    async def abort(self) -> None:
        if self.upload_id is not None:
            with contextlib.suppress(Exception):
                await self.client.abort_multipart_upload(Bucket=self.bucket, Key=self.key, UploadId=self.upload_id)

    async def _upload_part(self) -> None:
        if self.upload_id is None:
            created = await self.client.create_multipart_upload(Bucket=self.bucket, Key=self.key)
            self.upload_id = created["UploadId"]
        part_number = len(self.parts) + 1
        response = await self.client.upload_part(
            Bucket=self.bucket, Key=self.key, UploadId=self.upload_id, PartNumber=part_number, Body=bytes(self.buffer)
        )
        self.parts.append({"ETag": response["ETag"], "PartNumber": part_number})
        self.buffer.clear()


async def fetch_block(client: RecordingApiClient, block: Block, session: SessionRow, team_id: int) -> bytes:
    for attempt in range(1, BLOCK_FETCH_ATTEMPTS + 1):
        try:
            return await client.fetch_block(
                block.key, block.start_byte, block.end_byte, session.session_id, team_id, decompress=False
            )
        except BlockFetchError:
            if attempt == BLOCK_FETCH_ATTEMPTS:
                raise
            await asyncio.sleep(attempt)
    raise AssertionError("unreachable")


async def export_session(
    recordings: RecordingApiClient,
    s3: "S3Client",
    input: ExportShardInput,
    session: SessionRow,
    viewports: list[dict[str, Any]],
    person: dict[str, Any] | None,
) -> ManifestLine:
    line = functools.partial(
        ManifestLine,
        session_id=session.session_id,
        distinct_id=session.distinct_id,
        start_time=session.start_time.isoformat(),
        end_time=session.end_time.isoformat(),
    )
    if session.expired:
        return line(status="expired")
    if not session.blocks:
        return line(status="missing")

    key = session_key(input.destination, input.team_id, session.start_time, session.session_id)
    upload = SessionUpload(s3, input.destination.bucket, key)
    try:
        await upload.write(
            encode_header(
                {
                    "version": FILE_VERSION,
                    "session_id": session.session_id,
                    "team_id": input.team_id,
                    "distinct_id": session.distinct_id,
                    "start_time": session.start_time.isoformat(),
                    "end_time": session.end_time.isoformat(),
                    "person": person,
                    "viewports": viewports,
                    "exported_at": datetime.now(UTC).isoformat(),
                    "block_count": len(session.blocks),
                }
            )
        )
        # Fetch a window of blocks at a time and write them in order, so memory stays bounded for long sessions.
        for window_start in range(0, len(session.blocks), BLOCK_CONCURRENCY):
            window = session.blocks[window_start : window_start + BLOCK_CONCURRENCY]
            for data in await asyncio.gather(*(fetch_block(recordings, b, session, input.team_id) for b in window)):
                await upload.write(frame_block(data))
        await upload.finish()
    except RecordingDeletedError:
        await upload.abort()
        return line(status="deleted")
    except BlockFetchError:
        await upload.abort()
        return line(status="missing")
    except BaseException:
        await upload.abort()
        raise

    return line(
        status="exported",
        key=key,
        bytes=upload.size,
        sha256=upload.sha256.hexdigest(),
        block_count=len(session.blocks),
    )


def count(lines: Iterable[ManifestLine]) -> ExportTotals:
    totals = ExportTotals()
    for manifest_line in lines:
        totals = totals.add(
            ExportTotals(
                exported=int(manifest_line.status == "exported"),
                deleted=int(manifest_line.status == "deleted"),
                expired=int(manifest_line.status == "expired"),
                missing=int(manifest_line.status == "missing"),
                bytes=manifest_line.bytes,
            )
        )
    return totals


@activity.defn
async def export_shard(input: ExportShardInput) -> ExportTotals:
    tag_queries(product=Product.REPLAY, feature=Feature.MANAGEMENT_COMMAND, team_id=input.team_id)
    log = logger.bind(team_id=input.team_id, run_id=input.run_id, day=input.day, shard=input.shard)

    checkpoint = ShardCheckpoint(last_session_id="", manifest_parts=0, totals=ExportTotals())
    if activity.info().heartbeat_details:
        # Heartbeat details come back as plain dicts, because the converter has no type hint for them.
        details = activity.info().heartbeat_details[0]
        checkpoint = ShardCheckpoint(
            last_session_id=details["last_session_id"],
            manifest_parts=details["manifest_parts"],
            totals=ExportTotals(**details["totals"]),
        )

    sessions = [s for s in await sync_to_async(list_shard_sessions)(input) if s.session_id > checkpoint.last_session_id]
    log.info("export_recordings.shard_started", sessions=len(sessions), resumed_after=checkpoint.last_session_id)

    async with (
        Heartbeater(details=(checkpoint,)) as heartbeater,
        recording_api_client(connection_limit=RECORDING_API_CONNECTIONS) as recordings,
        destination_client(input.team_id, input.destination) as s3,
    ):
        semaphore = asyncio.Semaphore(SESSION_CONCURRENCY)

        async def export_one(session: SessionRow, viewports: list[dict[str, Any]], person: dict | None) -> ManifestLine:
            async with semaphore:
                return await export_session(recordings, s3, input, session, viewports, person)

        prefix = manifest_prefix(input.destination, input.team_id, input.run_id)
        for chunk_start in range(0, len(sessions), SESSIONS_PER_CHECKPOINT):
            chunk = sessions[chunk_start : chunk_start + SESSIONS_PER_CHECKPOINT]
            viewports, persons = await sync_to_async(load_session_metadata)(input.team_id, chunk)
            lines = await asyncio.gather(
                *(export_one(s, viewports.get(s.session_id, []), persons.get(s.distinct_id)) for s in chunk)
            )
            part = checkpoint.manifest_parts
            await s3.put_object(
                Bucket=input.destination.bucket,
                Key=f"{prefix}/{input.day}-{input.shard:04d}-{part:04d}.jsonl",
                Body="".join(manifest_line.to_json() + "\n" for manifest_line in lines).encode(),
            )
            checkpoint = ShardCheckpoint(
                last_session_id=chunk[-1].session_id,
                manifest_parts=part + 1,
                totals=checkpoint.totals.add(count(lines)),
            )
            heartbeater.details = (checkpoint,)

    log.info("export_recordings.shard_finished", totals=checkpoint.totals)
    return checkpoint.totals


@activity.defn
async def write_summary(input: WriteSummaryInput) -> None:
    quote_json = await sync_to_async(object_storage.read)(quote_storage_key(input.quote_id))
    if quote_json is None:
        raise ApplicationError(f"Quote {input.quote_id} does not exist", non_retryable=True)
    quoted_sessions = json.loads(quote_json)["sessions"]
    totals = input.totals
    listed = totals.exported + totals.deleted + totals.expired + totals.missing
    summary = {
        "run_id": input.run_id,
        "quote_id": input.quote_id,
        "workflow_id": input.workflow_id,
        "team_id": input.team_id,
        "date_from": input.date_from,
        "date_to": input.date_to,
        "shards_per_day": input.shards_per_day,
        "manifest_file_pattern": "{date}-{shard}-{part}.jsonl",
        "started_at": input.started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "sessions": {
            "exported": totals.exported,
            "deleted": totals.deleted,
            "expired": totals.expired,
            "missing": totals.missing,
            "quoted": quoted_sessions,
            # Sessions deleted between the quote and the run drop out of the listing.
            "deleted_before_run": max(quoted_sessions - listed, 0),
        },
        "bytes": totals.bytes,
    }
    prefix = manifest_prefix(input.destination, input.team_id, input.run_id)
    async with destination_client(input.team_id, input.destination) as s3:
        await s3.put_object(Bucket=input.destination.bucket, Key=f"{prefix}/quote.json", Body=quote_json.encode())
        await s3.put_object(
            Bucket=input.destination.bucket, Key=f"{prefix}/summary.json", Body=json.dumps(summary).encode()
        )
