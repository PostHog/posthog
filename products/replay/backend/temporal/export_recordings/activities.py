import re
import json
import asyncio
import hashlib
import functools
import contextlib
import collections
import dataclasses
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import structlog
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.execute import ClickHouseExternalTable
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.session_recordings.recordings.errors import BlockFetchError, BlockNotFoundError, RecordingDeletedError
from posthog.session_recordings.recordings.recording_api_client import RecordingApiClient, recording_api_client
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async_pool
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
BLOCK_RETRY_DELAY_SECONDS = 1.0
RECORDING_API_CONNECTIONS = SESSION_CONCURRENCY * BLOCK_CONCURRENCY
# S3 needs at least 5 MiB for every multipart part except the last.
UPLOAD_PART_BYTES = 8 * 1024 * 1024
SESSIONS_PER_CHECKPOINT = 500
METADATA_BATCH_SIZE = 100
VIEWPORT_ROW_LIMIT = 50000

# Formats that cannot carry an IAM wildcard into the session policy.
BUCKET_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
KMS_KEY_PATTERN = re.compile(r"^(arn:aws[a-z-]*:kms:[a-z0-9-]+:\d{12}:key/)?[A-Za-z0-9-]+$")
BLOCK_URL_PATTERN = re.compile(r"^s3://[^/]+/(?P<key>[^?]+)\?range=bytes=(?P<start>\d+)-(?P<end>\d+)$")

NON_RETRYABLE_ERRORS = (InvalidCredentialsError, S3IntegrationNotFoundError, ExternalRoleArnNotConfiguredError)

# Same rule as recording-api's listBlocks. Needs `start_time` and the session's grouped rows.
SESSION_EXPIRY_TIME_SQL = "dateTrunc('DAY', start_time) + toIntervalDay(coalesce(max(retention_period_days), 30))"

# A session that crosses midnight has rows on two days. Reading the day before finds its true start,
# and reading the day after finds its later rows.
# One page of a shard's sessions after a session ID, so a shard never holds all its block references at once.
SHARD_SESSIONS_QUERY = f"""
SELECT
    session_id,
    any(distinct_id),
    min(min_first_timestamp) AS start_time,
    max(max_last_timestamp),
    groupArrayArray(block_first_timestamps),
    groupArrayArray(block_urls),
    {SESSION_EXPIRY_TIME_SQL} AS expiry_time
FROM session_replay_events
PREWHERE team_id = %(team_id)s
    AND min_first_timestamp >= %(day_start)s - INTERVAL 1 DAY
    AND min_first_timestamp < %(day_start)s + INTERVAL 2 DAY
WHERE cityHash64(session_id) %% %(shards_per_day)s = %(shard)s
    AND session_id > %(after)s
    {{session_filter}}
GROUP BY session_id
HAVING max(is_deleted) = 0
    AND start_time >= %(day_start)s
    AND start_time < %(day_start)s + INTERVAL 1 DAY
    AND expiry_time >= %(quoted_at)s
ORDER BY session_id
LIMIT %(limit)s
"""
SELECTED_SESSIONS_TABLE = "selected_sessions"

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
LIMIT {limit}
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
    expiry_time: datetime


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
        return json.dumps(dataclasses.asdict(self))


@frozen
class ShardCheckpoint:
    last_session_id: str = ""
    manifest_parts: int = 0
    totals: ExportTotals = ExportTotals()


def run_prefix(destination: ExportDestination, team_id: int) -> str:
    return f"{destination.prefix.strip('/')}/{team_id}".lstrip("/")


def manifest_prefix(destination: ExportDestination, team_id: int, run_id: str) -> str:
    return f"{run_prefix(destination, team_id)}/{run_id}/manifests"


def session_key(
    destination: ExportDestination, team_id: int, run_id: str, start_time: datetime, session_id: str
) -> str:
    return f"{run_prefix(destination, team_id)}/{run_id}/{start_time:%Y-%m-%d}/{session_id}.{FILE_EXTENSION}"


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


def list_shard_sessions(input: ExportShardInput, after: str = "") -> list[SessionRow]:
    session_filter = ""
    external_tables: list[ClickHouseExternalTable] | None = None
    if input.session_ids_key:
        # A session list goes as an external table, so its size never meets the query size limit.
        session_filter = f"AND session_id IN {SELECTED_SESSIONS_TABLE}"
        external_tables = [
            ClickHouseExternalTable(
                name=SELECTED_SESSIONS_TABLE,
                structure=[("session_id", "String")],
                data=[{"session_id": session_id} for session_id in load_session_ids(input.session_ids_key)],
            )
        ]
    rows = sync_execute(
        SHARD_SESSIONS_QUERY.replace("{session_filter}", session_filter),
        {
            "team_id": input.team_id,
            "day_start": datetime.fromisoformat(input.day).replace(tzinfo=UTC),
            "shards_per_day": input.shards_per_day,
            "shard": input.shard,
            "quoted_at": datetime.fromisoformat(input.quoted_at),
            "after": after,
            "limit": SESSIONS_PER_CHECKPOINT,
        },
        workload=Workload.OFFLINE,
        external_tables=external_tables,
    )
    return [
        SessionRow(
            session_id=session_id,
            distinct_id=distinct_id,
            start_time=start_time.replace(tzinfo=UTC),
            end_time=end_time.replace(tzinfo=UTC),
            blocks=parse_blocks(first_timestamps, urls),
            expiry_time=expiry_time.replace(tzinfo=UTC),
        )
        for session_id, distinct_id, start_time, end_time, first_timestamps, urls, expiry_time in rows
    ]


@functools.lru_cache(maxsize=8)
def load_session_ids(key: str) -> frozenset[str]:
    content = object_storage.read(key)
    if content is None:
        raise ApplicationError(f"Session ID list {key} does not exist", non_retryable=True)
    return frozenset(line.strip() for line in content.splitlines() if line.strip())


SessionMetadata = tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]


def load_viewports(team: Team, sessions: list[SessionRow], viewports: dict[str, list[dict[str, Any]]]) -> None:
    rows = execute_hogql_query(
        parse_select(VIEWPORTS_QUERY),
        team,
        placeholders={
            "start": ast.Constant(value=min(s.start_time for s in sessions) - timedelta(minutes=5)),
            "end": ast.Constant(value=max(s.end_time for s in sessions) + timedelta(minutes=5)),
            "session_ids": ast.Constant(value=[s.session_id for s in sessions]),
            "limit": ast.Constant(value=VIEWPORT_ROW_LIMIT),
        },
        limit_context=LimitContext.EXPORT,
        workload=Workload.OFFLINE,
    ).results
    if len(rows) >= VIEWPORT_ROW_LIMIT and len(sessions) > 1:
        # The batch hit the row limit, so some sessions would get partial viewports. Query each half instead.
        middle = len(sessions) // 2
        load_viewports(team, sessions[:middle], viewports)
        load_viewports(team, sessions[middle:], viewports)
        return
    if len(rows) >= VIEWPORT_ROW_LIMIT:
        logger.warning("export_recordings.viewports_truncated", session_id=sessions[0].session_id)
    for session_id, timestamp, width, height, href in rows:
        viewports.setdefault(session_id, []).append(
            {"timestamp": timestamp, "width": width, "height": height, "href": href}
        )


def load_session_metadata(team_id: int, sessions: list[SessionRow]) -> SessionMetadata:
    """Return the viewports per session and the person per distinct ID, which file playback cannot load."""
    team = Team.objects.get(id=team_id)
    viewports: dict[str, list[dict[str, Any]]] = {}
    persons: dict[str, dict[str, Any]] = {}
    for batch_start in range(0, len(sessions), METADATA_BATCH_SIZE):
        batch = sessions[batch_start : batch_start + METADATA_BATCH_SIZE]
        load_viewports(team, batch, viewports)
        person_rows = execute_hogql_query(
            parse_select(PERSONS_QUERY),
            team,
            placeholders={"distinct_ids": ast.Constant(value=sorted({s.distinct_id for s in batch}))},
            limit_context=LimitContext.EXPORT,
            workload=Workload.OFFLINE,
        ).results
        for distinct_id, person_id, created_at, properties in person_rows:
            persons[distinct_id] = {
                "id": str(person_id),
                "uuid": str(person_id),
                "distinct_ids": [distinct_id],
                "created_at": created_at.isoformat() if created_at else None,
                "properties": json.loads(properties) if isinstance(properties, str) else properties,
            }
    return viewports, persons


async def resolve_s3_credentials(
    team_id: int, destination: ExportDestination
) -> tuple[AWSCredentials, Callable[[], Coroutine[Any, Any, AWSCredentials]], str]:
    """Return the assumed role's credentials, how to refresh them and the role's AWS account ID."""
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
        policy_statements=policy_statements(destination, team_id, aws_role_arn),
    )
    return await refresh_using(), refresh_using, role_account_id(aws_role_arn)


def role_account_id(aws_role_arn: str) -> str:
    parts = aws_role_arn.split(":")
    if len(parts) < 6 or not parts[4]:
        raise ApplicationError(f"Malformed role ARN {aws_role_arn!r}", non_retryable=True)
    return parts[4]


def destination_error(destination: ExportDestination) -> str | None:
    """Return why the destination is not allowed, or None."""
    if not BUCKET_NAME_PATTERN.match(destination.bucket):
        return f"{destination.bucket!r} is not a valid S3 bucket name"
    if any(character in destination.prefix for character in "*?"):
        return "The prefix must not contain * or ?"
    if destination.kms_key_id and not KMS_KEY_PATTERN.match(destination.kms_key_id):
        return "The KMS key must be a key ID or a key ARN, not an alias or a pattern"
    return None


def policy_statements(destination: ExportDestination, team_id: int, aws_role_arn: str) -> list[PolicyStatement]:
    if error := destination_error(destination):
        raise ApplicationError(error, non_retryable=True)
    statements = [
        PolicyStatement(
            Effect="Allow",
            Action=["s3:PutObject", "s3:AbortMultipartUpload"],
            Resource=f"arn:aws:s3:::{destination.bucket}/{run_prefix(destination, team_id)}/*",
        )
    ]
    if destination.kms_key_id:
        # Completing a multipart upload decrypts each part's data key, so the role needs kms:Decrypt too.
        statements.append(
            PolicyStatement(
                Effect="Allow",
                Action=["kms:GenerateDataKey", "kms:Decrypt"],
                Resource=kms_key_arn(destination.kms_key_id, destination.region, aws_role_arn),
            )
        )
    return statements


def kms_key_arn(kms_key_id: str, region: str, aws_role_arn: str) -> str:
    if kms_key_id.startswith("arn:"):
        return kms_key_id
    # S3 reads a bare key ID as a key in the account that makes the request, which is the role's account.
    return f"arn:aws:kms:{region}:{role_account_id(aws_role_arn)}:key/{kms_key_id}"


class CustomerBucket:
    """Writes to the customer's bucket. Every request names the bucket owner, so S3 refuses a bucket of another account."""

    def __init__(self, client: "S3Client", destination: ExportDestination, owner_account_id: str) -> None:
        self.client = client
        self.target: dict[str, Any] = {"Bucket": destination.bucket, "ExpectedBucketOwner": owner_account_id}
        self.encryption: dict[str, Any] = (
            {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": destination.kms_key_id} if destination.kms_key_id else {}
        )

    async def put(self, key: str, body: bytes | bytearray) -> None:
        # botocore accepts a bytearray body, so a buffer goes out without a copy. The type stubs list bytes only.
        await self.client.put_object(**self.target, Key=key, Body=cast(bytes, body), **self.encryption)

    async def create_multipart_upload(self, key: str) -> str:
        created = await self.client.create_multipart_upload(**self.target, Key=key, **self.encryption)
        return created["UploadId"]

    async def upload_part(self, key: str, upload_id: str, part_number: int, body: bytearray) -> str:
        response = await self.client.upload_part(
            **self.target, Key=key, UploadId=upload_id, PartNumber=part_number, Body=cast(bytes, body)
        )
        return response["ETag"]

    async def complete_multipart_upload(self, key: str, upload_id: str, parts: list["CompletedPartTypeDef"]) -> None:
        await self.client.complete_multipart_upload(
            **self.target, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts}
        )

    async def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        await self.client.abort_multipart_upload(**self.target, Key=key, UploadId=upload_id)


@contextlib.asynccontextmanager
async def customer_bucket(team_id: int, destination: ExportDestination) -> AsyncIterator[CustomerBucket]:
    try:
        credentials, refresh_using, owner_account_id = await resolve_s3_credentials(team_id, destination)
        async with s3_client(credentials, destination.region, refresh_using=refresh_using) as client:
            yield CustomerBucket(client, destination, owner_account_id)
    except NON_RETRYABLE_ERRORS as e:
        raise ApplicationError(str(e), non_retryable=True) from e


class SessionUpload:
    """Streams one session file to S3: a single PUT when small, a multipart upload otherwise."""

    def __init__(self, bucket: CustomerBucket, key: str) -> None:
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
            await self.bucket.put(self.key, self.buffer)
            return
        if self.buffer:
            await self._upload_part()
        await self.bucket.complete_multipart_upload(self.key, self.upload_id, self.parts)

    async def abort(self) -> None:
        if self.upload_id is not None:
            with contextlib.suppress(Exception):
                await self.bucket.abort_multipart_upload(self.key, self.upload_id)

    async def _upload_part(self) -> None:
        if self.upload_id is None:
            self.upload_id = await self.bucket.create_multipart_upload(self.key)
        part_number = len(self.parts) + 1
        # Hand the buffer over instead of copying it, so a session holds one part in memory.
        body, self.buffer = self.buffer, bytearray()
        etag = await self.bucket.upload_part(self.key, self.upload_id, part_number, body)
        self.parts.append({"ETag": etag, "PartNumber": part_number})


async def fetch_block(client: RecordingApiClient, block: Block, session: SessionRow, team_id: int) -> bytes:
    fetch = functools.partial(
        client.fetch_block, block.key, block.start_byte, block.end_byte, session.session_id, team_id, decompress=False
    )
    for attempt in range(1, BLOCK_FETCH_ATTEMPTS):
        try:
            return await fetch()
        except BlockNotFoundError:
            raise
        # The client raises TimeoutError, not BlockFetchError, when a block takes longer than its total timeout.
        except (BlockFetchError, TimeoutError):
            await asyncio.sleep(attempt * BLOCK_RETRY_DELAY_SECONDS)
    return await fetch()


async def fetch_blocks_in_order(client: RecordingApiClient, session: SessionRow, team_id: int) -> AsyncGenerator[bytes]:
    """Yield the session's blocks in order, keeping up to BLOCK_CONCURRENCY fetches in flight."""
    pending: collections.deque[asyncio.Task[bytes]] = collections.deque()
    try:
        for block in session.blocks or []:
            pending.append(asyncio.create_task(fetch_block(client, block, session, team_id)))
            if len(pending) == BLOCK_CONCURRENCY:
                yield await pending.popleft()
        while pending:
            yield await pending.popleft()
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


async def export_session(
    recordings: RecordingApiClient,
    bucket: CustomerBucket,
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
    # A shard can run for hours, so check expiry when the session's turn comes, not when the shard listed it.
    if session.expiry_time < datetime.now(UTC):
        return line(status="expired")
    if not session.blocks:
        return line(status="missing")

    key = session_key(input.destination, input.team_id, input.run_id, session.start_time, session.session_id)
    upload = SessionUpload(bucket, key)
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
        async with contextlib.aclosing(fetch_blocks_in_order(recordings, session, input.team_id)) as blocks:
            async for data in blocks:
                await upload.write(frame_block(data))
        await upload.finish()
    except RecordingDeletedError:
        await upload.abort()
        return line(status="deleted")
    except BlockNotFoundError:
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


def count(lines: list[ManifestLine]) -> ExportTotals:
    statuses: collections.Counter[str] = collections.Counter(manifest_line.status for manifest_line in lines)
    return ExportTotals(**statuses, bytes=sum(manifest_line.bytes for manifest_line in lines))


@activity.defn
async def export_shard(input: ExportShardInput) -> ExportTotals:
    tag_queries(product=Product.REPLAY, feature=Feature.MANAGEMENT_COMMAND, team_id=input.team_id)
    log = logger.bind(team_id=input.team_id, run_id=input.run_id, day=input.day, shard=input.shard)

    checkpoint = ShardCheckpoint()
    if activity.info().heartbeat_details:
        # Heartbeat details come back as plain dicts, because the converter has no type hint for them.
        details = activity.info().heartbeat_details[0]
        checkpoint = ShardCheckpoint(**{**details, "totals": ExportTotals(**details["totals"])})
    log.info("export_recordings.shard_started", resumed_after=checkpoint.last_session_id)

    def load_page(after: str) -> asyncio.Task[tuple[list[SessionRow], SessionMetadata]]:
        def load() -> tuple[list[SessionRow], SessionMetadata]:
            sessions = list_shard_sessions(input, after=after)
            return sessions, load_session_metadata(input.team_id, sessions) if sessions else ({}, {})

        return asyncio.create_task(database_sync_to_async_pool(load)())

    # Heartbeat from the start: the first listing can take minutes on a large day.
    async with Heartbeater(details=(checkpoint,)) as heartbeater:
        page = load_page(checkpoint.last_session_id)
        async with (
            recording_api_client(connection_limit=RECORDING_API_CONNECTIONS) as recordings,
            customer_bucket(input.team_id, input.destination) as bucket,
        ):
            semaphore = asyncio.Semaphore(SESSION_CONCURRENCY)

            async def export_one(
                session: SessionRow, viewports: list[dict[str, Any]], person: dict | None
            ) -> ManifestLine:
                async with semaphore:
                    return await export_session(recordings, bucket, input, session, viewports, person)

            prefix = manifest_prefix(input.destination, input.team_id, input.run_id)
            while True:
                chunk, (viewports, persons) = await page
                if not chunk:
                    break
                # The next page lists and loads its metadata while this page exports.
                page = load_page(chunk[-1].session_id)
                # A failed session cancels the rest of the page, and each cancelled session aborts its upload.
                # Temporal then retries the shard from the last checkpoint.
                try:
                    async with asyncio.TaskGroup() as group:
                        tasks = [
                            group.create_task(
                                export_one(s, viewports.get(s.session_id, []), persons.get(s.distinct_id))
                            )
                            for s in chunk
                        ]
                except ExceptionGroup as e:
                    page.cancel()
                    raise e.exceptions[0] from e
                lines = [task.result() for task in tasks]
                part = checkpoint.manifest_parts
                await bucket.put(
                    f"{prefix}/{input.day}-{input.shard:04d}-{part:04d}.jsonl",
                    "".join(manifest_line.to_json() + "\n" for manifest_line in lines).encode(),
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
    quote_json = await database_sync_to_async_pool(object_storage.read)(quote_storage_key(input.quote_id))
    if quote_json is None:
        raise ApplicationError(f"Quote {input.quote_id} does not exist", non_retryable=True)
    quote = json.loads(quote_json)
    quoted_sessions = quote["usage"]["sessions"]
    totals = input.totals
    listed = totals.exported + totals.deleted + totals.expired + totals.missing
    summary = {
        "run_id": input.run_id,
        "quote_id": input.quote_id,
        "workflow_id": activity.info().workflow_id,
        "team_id": input.team_id,
        "date_from": quote["date_from"],
        "date_to": quote["date_to"],
        "shards_per_day": input.shards_per_day,
        "manifest_file_pattern": "{date}-{shard}-{part}.jsonl",
        # Shards that failed after every retry. Rerun them with --shards.
        "failed_shards": list(input.failed_shards),
        "started_at": input.started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "sessions": {
            "exported": totals.exported,
            "deleted": totals.deleted,
            "expired": totals.expired,
            "missing": totals.missing,
            "quoted": quoted_sessions,
            # Sessions deleted between the quote and the run drop out of the listing. A run that skipped
            # shards, by failure or by --shards, cannot tell them apart from the skipped sessions.
            "deleted_before_run": max(quoted_sessions - listed, 0) if input.complete else None,
        },
        "bytes": totals.bytes,
    }
    prefix = manifest_prefix(input.destination, input.team_id, input.run_id)
    async with customer_bucket(input.team_id, input.destination) as bucket:
        # The customer gets the selection and the usage. Our cost stays out of their bucket.
        customer_quote = {key: value for key, value in quote.items() if key != "cost"}
        await bucket.put(f"{prefix}/quote.json", json.dumps(customer_quote, indent=2).encode())
        await bucket.put(f"{prefix}/summary.json", json.dumps(summary).encode())
