import io
import re
import gzip
import json
import bisect
import asyncio
import hashlib
import tempfile
import functools
import contextlib
import collections
import dataclasses
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import IO, TYPE_CHECKING, Any, cast

from django.conf import settings

import structlog
from botocore.exceptions import ClientError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.integration.aws import AWS_ROLE_ARN_RE, validate_aws_role_arn
from posthog.models.integration.common import IntegrationError
from posthog.session_recordings.recordings.errors import BlockFetchError, BlockNotFoundError, RecordingDeletedError
from posthog.session_recordings.recordings.recording_api_client import RecordingApiClient, recording_api_client
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater

from products.batch_exports.backend.facade.contracts import AWSCredentials
from products.batch_exports.backend.facade.destinations.s3 import (
    ExternalRoleArnNotConfiguredError,
    InvalidCredentialsError,
    PolicyStatement,
    get_credentials_using_user_aws_role,
    s3_client,
)
from products.replay.backend.temporal.export_recordings.types import (
    CheckDestinationInput,
    DayViewportsInput,
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
PERSON_ROW_LIMIT = 50000
VIEWPORTS_QUERY_TIMEOUT_SECONDS = 2 * 60 * 60
VIEWPORTS_GROUP_BY_SPILL_BYTES = 10 * 1024 * 1024 * 1024
# Senders choose the URLs, so both caps keep a team's own events from growing worker memory without bound.
# File playback refuses a header over 8 MiB, and a session's viewports stay well under it.
MAX_SESSION_VIEWPORT_BYTES = 64 * 1024
# A shard reads its whole file into memory, so the file stays bounded too.
MAX_SHARD_VIEWPORT_BYTES = 256 * 1024 * 1024
# A narrow selection filters its sessions in the query, so ClickHouse aggregates no others.
MAX_FILTERED_SESSIONS = 10_000
SHARD_BLOCK_BUFFER_BYTES = 256 * 1024 * 1024

# Formats that cannot carry an IAM wildcard into the session policy.
BUCKET_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
KMS_KEY_PATTERN = re.compile(r"^(arn:aws[a-z-]*:kms:[a-z0-9-]+:\d{12}:key/)?[A-Za-z0-9-]+$")
BLOCK_URL_PATTERN = re.compile(r"^s3://[^/]+/(?P<key>[^?]+)\?range=bytes=(?P<start>\d+)-(?P<end>\d+)$")

# Our cost and storage paths stay out of the customer's bucket.
CUSTOMER_QUOTE_FIELDS = ("quote_id", "team_id", "date_from", "date_to", "selection", "created_at", "usage")

# S3 returns these with a 4xx status, but a later attempt can succeed.
TRANSIENT_S3_ERROR_CODES = frozenset({"RequestTimeout", "SlowDown", "Throttling", "ThrottlingException"})

NON_RETRYABLE_ERRORS = (InvalidCredentialsError, ExternalRoleArnNotConfiguredError)

# Same rule as recording-api's listBlocks. Needs `start_time` and the session's grouped rows.
SESSION_EXPIRY_TIME_SQL = "dateTrunc('DAY', start_time) + toIntervalDay(coalesce(max(retention_period_days), 30))"

# A session that crosses midnight has rows on two days, so the day before and the day after are read too.
# The quote already fixed each session's day, so a start that moves later does not drop it.
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
WHERE session_id IN %(session_ids)s
GROUP BY session_id
HAVING max(is_deleted) = 0
ORDER BY session_id
"""

# One query reads a day's viewports for all its shards, because events has no session ID in its sort key and
# so every viewport query scans its whole time range. The event filter is in the sort key, so ClickHouse reads
# only those events. A session lasts at most a day, so two days hold every event of the sessions that started
# on the first, and the hour before catches a first pageview stamped just ahead of the recording. A row per viewport state and minute keeps the result small and still follows resizes.
DAY_VIEWPORTS_QUERY = """
SELECT
    cityHash64(`$session_id`) % {shards_per_day} AS shard,
    `$session_id` AS session_id,
    toUnixTimestamp64Milli(min(timestamp)) AS first_ms,
    toString(properties.$viewport_width) AS width,
    toString(properties.$viewport_height) AS height,
    -- A long URL would break the line-by-line read.
    left(toString(properties.$current_url), 4096) AS href
FROM events
WHERE event IN ('$pageview', '$screen')
    AND timestamp >= {start} AND timestamp < {end}
    -- Session IDs and dimensions come from senders, so bounding them keeps every line short and playable.
    AND length(`$session_id`) BETWEEN 1 AND 128
    AND match(toString(properties.$viewport_width), '^[0-9]{1,6}$')
    AND match(toString(properties.$viewport_height), '^[0-9]{1,6}$')
    AND {session_filter}
GROUP BY shard, session_id, width, height, href, toStartOfMinute(timestamp)
ORDER BY shard, session_id, first_ms
"""

# Two lookups on the sort keys. Joining person onto person_distinct_ids instead reads all of the team's persons.
PERSON_IDS_QUERY = """
SELECT distinct_id, person_id
FROM person_distinct_ids
WHERE distinct_id IN {distinct_ids}
LIMIT {limit}
"""

PERSONS_QUERY = """
SELECT id, created_at, properties
FROM persons
WHERE id IN {person_ids}
LIMIT {limit}
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


def session_ids_shard_key(prefix: str, day: str, shard: int) -> str:
    return f"{prefix}/{day}/{shard:04d}.txt"


def viewports_day_prefix(team_id: int, run_id: str, day: str) -> str:
    return f"session_recording_exports/viewports/{team_id}/{run_id}/{day}"


def viewports_shard_key(team_id: int, run_id: str, day: str, shard: int) -> str:
    return f"{viewports_day_prefix(team_id, run_id, day)}/{shard:04d}.jsonl.gz"


def list_shard_sessions(input: ExportShardInput, listed: tuple[str, ...], after: str = "") -> list[SessionRow]:
    """Return the next page of the shard's listed sessions after a session ID, skipping deleted ones."""
    remaining = listed[bisect.bisect_right(listed, after) :]
    # A page can come back empty when all its sessions were deleted, so keep going until one has rows.
    for start in range(0, len(remaining), SESSIONS_PER_CHECKPOINT):
        rows = sync_execute(
            SHARD_SESSIONS_QUERY,
            {
                "team_id": input.team_id,
                "day_start": datetime.fromisoformat(input.day).replace(tzinfo=UTC),
                "session_ids": remaining[start : start + SESSIONS_PER_CHECKPOINT],
            },
            workload=Workload.OFFLINE,
        )
        if rows:
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
    return []


def load_shard_session_ids(session_ids_prefix: str, day: str, shard: int) -> tuple[str, ...]:
    key = session_ids_shard_key(session_ids_prefix, day, shard)
    # read() returns None for an empty file too, and a shard without sessions has one.
    content = object_storage.read_bytes(key, missing_ok=True)
    if content is None:
        raise ApplicationError(f"Session ID list {key} does not exist", non_retryable=True)
    return tuple(sorted({line.strip() for line in content.decode().splitlines() if line.strip()}))


Viewport = dict[str, Any]
SessionMetadata = tuple[dict[str, list[Viewport]], dict[str, dict[str, Any]]]


def day_session_filter(input: DayViewportsInput) -> ast.Expr:
    listed: list[str] = []
    for shard in range(input.shards_per_day):
        listed.extend(load_shard_session_ids(input.session_ids_prefix, input.day, shard))
        if len(listed) > MAX_FILTERED_SESSIONS:
            return ast.Constant(value=True)
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["$session_id"]),
        right=ast.Constant(value=listed),
    )


def day_viewports_sql(team: Team, input: DayViewportsInput) -> tuple[str, dict[str, Any]]:
    day_start = datetime.fromisoformat(input.day).replace(tzinfo=UTC)
    context = HogQLContext(team_id=team.pk, team=team, enable_select_queries=True, limit_top_select=False)
    context.output_format = "JSONEachRow"
    sql, _ = prepare_and_print_ast(
        parse_select(
            DAY_VIEWPORTS_QUERY,
            placeholders={
                "shards_per_day": ast.Constant(value=input.shards_per_day),
                "start": ast.Constant(value=day_start - timedelta(hours=1)),
                "end": ast.Constant(value=day_start + timedelta(days=2)),
                "session_filter": day_session_filter(input),
            },
        ),
        context,
        "clickhouse",
        settings=HogQLGlobalSettings(
            max_execution_time=VIEWPORTS_QUERY_TIMEOUT_SECONDS,
            max_bytes_before_external_group_by=VIEWPORTS_GROUP_BY_SPILL_BYTES,
        ),
    )
    return sql, context.values


class ViewportFileWriter:
    """Writes each shard's viewports, sorted by session ID, keeping only the sessions the shard exports."""

    def __init__(self, input: DayViewportsInput) -> None:
        self.input = input
        self.written: set[int] = set()
        self.shard: int | None = None
        self.listed: frozenset[str] = frozenset()
        self.rows = 0
        self.dropped = 0
        self.session_id = ""
        self.session_bytes = 0
        self.shard_bytes = 0
        self.buffer: IO[bytes] = tempfile.TemporaryFile()
        self.file = gzip.GzipFile(fileobj=self.buffer, mode="wb")

    async def add(self, row: dict[str, Any]) -> None:
        shard = int(row["shard"])
        if shard != self.shard:
            await self.flush()
            self.shard = shard
            self.listed = frozenset(
                await database_sync_to_async_pool(load_shard_session_ids)(
                    self.input.session_ids_prefix, self.input.day, shard
                )
            )
        if row["session_id"] not in self.listed:
            return
        if row["session_id"] != self.session_id:
            self.session_id, self.session_bytes = row["session_id"], 0
        viewport = {
            # JSONEachRow quotes 64-bit integers, and file playback needs a number.
            "timestamp": int(row["first_ms"]),
            "width": row["width"],
            "height": row["height"],
            "href": row["href"],
        }
        line = json.dumps([row["session_id"], viewport]).encode() + b"\n"
        self.session_bytes += len(line)
        if self.session_bytes > MAX_SESSION_VIEWPORT_BYTES or self.shard_bytes + len(line) > MAX_SHARD_VIEWPORT_BYTES:
            self.dropped += 1
            return
        self.shard_bytes += len(line)
        self.file.write(line)
        self.rows += 1

    async def flush(self) -> None:
        if self.shard is not None:
            key = viewports_shard_key(self.input.team_id, self.input.run_id, self.input.day, self.shard)
            self.file.close()
            self.buffer.seek(0)
            await database_sync_to_async_pool(object_storage.write_stream)(key, self.buffer)
            self.written.add(self.shard)
        self.buffer.close()
        self.shard = None
        self.shard_bytes = 0
        self.buffer = tempfile.TemporaryFile()
        self.file = gzip.GzipFile(fileobj=self.buffer, mode="wb")

    async def finish(self) -> None:
        await self.flush()
        # Every shard gets a file, so a shard that finds none knows this activity did not run.
        for shard in range(self.input.shards_per_day):
            if shard not in self.written:
                self.shard = shard
                await self.flush()
        self.file.close()
        self.buffer.close()


@activity.defn
async def load_day_viewports(input: DayViewportsInput) -> None:
    tag_queries(product=Product.REPLAY, feature=Feature.MANAGEMENT_COMMAND, team_id=input.team_id)
    done_key = f"{viewports_day_prefix(input.team_id, input.run_id, input.day)}/done"
    # A day whose shards straddle a continue-as-new comes here twice in the same run.
    if await database_sync_to_async_pool(object_storage.read_bytes)(done_key, missing_ok=True) is not None:
        return
    team = await Team.objects.aget(id=input.team_id)
    sql, values = await database_sync_to_async_pool(day_viewports_sql)(team, input)
    writer = ViewportFileWriter(input)
    async with Heartbeater(), get_client(team_id=input.team_id, workload=Workload.OFFLINE) as client:
        # Reading line by line keeps the day's rows out of memory.
        async with client.apost_query(sql, query_parameters=values, query_id=None) as response:
            async for line in response.content:
                if line.strip():
                    await writer.add(json.loads(line))
        await writer.finish()
    await database_sync_to_async_pool(object_storage.write)(done_key, b"done")
    logger.info(
        "export_recordings.day_viewports_loaded",
        team_id=input.team_id,
        day=input.day,
        rows=writer.rows,
        dropped=writer.dropped,
    )


class ViewportReader:
    """Reads a shard's viewport file in session ID order, alongside the shard's pages."""

    def __init__(self, content: bytes) -> None:
        self.lines = gzip.GzipFile(fileobj=io.BytesIO(content), mode="rb")
        self.pending: tuple[str, Viewport] | None = None

    @classmethod
    def load(cls, team_id: int, run_id: str, day: str, shard: int) -> "ViewportReader":
        key = viewports_shard_key(team_id, run_id, day, shard)
        content = object_storage.read_bytes(key, missing_ok=True)
        if content is None:
            raise ApplicationError(f"Viewport file {key} does not exist", non_retryable=True)
        return cls(content)

    def take(self, first_session_id: str, last_session_id: str) -> dict[str, list[Viewport]]:
        """Return the viewports of the sessions between two session IDs, inclusive, and skip past them."""
        viewports: dict[str, list[Viewport]] = {}
        while True:
            if self.pending is None:
                line = self.lines.readline()
                if not line:
                    return viewports
                session_id, viewport = json.loads(line)
                self.pending = (session_id, viewport)
            session_id, viewport = self.pending
            if session_id > last_session_id:
                return viewports
            # A resumed shard starts mid-file, so the sessions it already exported are skipped.
            if session_id >= first_session_id:
                viewports.setdefault(session_id, []).append(viewport)
            self.pending = None


def load_persons(team: Team, distinct_ids: list[str]) -> dict[str, dict[str, Any]]:
    person_ids = execute_hogql_query(
        parse_select(PERSON_IDS_QUERY),
        team,
        placeholders={"distinct_ids": ast.Constant(value=distinct_ids), "limit": ast.Constant(value=PERSON_ROW_LIMIT)},
        limit_context=LimitContext.EXPORT,
        workload=Workload.OFFLINE,
    ).results
    if not person_ids:
        return {}
    rows = execute_hogql_query(
        parse_select(PERSONS_QUERY),
        team,
        placeholders={
            "person_ids": ast.Constant(value=sorted({str(person_id) for _, person_id in person_ids})),
            "limit": ast.Constant(value=PERSON_ROW_LIMIT),
        },
        limit_context=LimitContext.EXPORT,
        workload=Workload.OFFLINE,
    ).results
    persons = {
        str(person_id): {
            "id": str(person_id),
            "uuid": str(person_id),
            "created_at": created_at.isoformat() if created_at else None,
            "properties": json.loads(properties) if isinstance(properties, str) else properties,
        }
        for person_id, created_at, properties in rows
    }
    return {
        distinct_id: {**persons[str(person_id)], "distinct_ids": [distinct_id]}
        for distinct_id, person_id in person_ids
        if str(person_id) in persons
    }


def load_session_metadata(team_id: int, sessions: list[SessionRow], viewports: ViewportReader) -> SessionMetadata:
    """Return the viewports per session and the person per distinct ID, which file playback cannot load."""
    team = Team.objects.get(id=team_id)
    viewports_by_session = viewports.take(sessions[0].session_id, sessions[-1].session_id)
    return viewports_by_session, load_persons(team, sorted({s.distinct_id for s in sessions}))


@frozen
class RoleCredentials:
    credentials: AWSCredentials
    refresh_using: Callable[[], Coroutine[Any, Any, AWSCredentials]]
    owner_account_id: str


async def resolve_s3_credentials(team_id: int, destination: ExportDestination, run_id: str) -> RoleCredentials:
    """Assume the customer's role, scoped to this run's folder in their bucket."""
    team = await Team.objects.aget(id=team_id)
    refresh_using = functools.partial(
        get_credentials_using_user_aws_role,
        destination.role_arn,
        external_id(team.organization_id),
        session_name=f"PostHog-replay-export-{team_id}",
        policy_statements=policy_statements(destination, team_id, run_id),
        # Recording exports have their own external-access role, separate from batch exports.
        external_role_arn=settings.RECORDING_EXPORT_S3_EXTERNAL_ROLE_ARN,
    )
    return RoleCredentials(
        credentials=await refresh_using(),
        refresh_using=refresh_using,
        owner_account_id=role_account_id(destination.role_arn),
    )


def external_id(organization_id: object) -> str:
    return f"posthog-{organization_id}"


def role_account_id(aws_role_arn: str) -> str:
    # destination_error has already matched the ARN against AWS_ROLE_ARN_RE.
    return aws_role_arn.split(":")[4]


def destination_error(destination: ExportDestination) -> str | None:
    """Return why the destination is not allowed, or None."""
    # The session policy and KMS key ARNs are built for the aws partition only.
    if not AWS_ROLE_ARN_RE.match(destination.role_arn) or not destination.role_arn.startswith("arn:aws:"):
        return f"{destination.role_arn!r} is not a valid IAM role ARN in the aws partition"
    if not BUCKET_NAME_PATTERN.match(destination.bucket):
        return f"{destination.bucket!r} is not a valid S3 bucket name"
    if any(character in destination.prefix for character in "*?"):
        return "The prefix must not contain * or ?"
    if destination.kms_key_id and not KMS_KEY_PATTERN.match(destination.kms_key_id):
        return "The KMS key must be a key ID or a key ARN, not an alias or a pattern"
    return None


def policy_statements(destination: ExportDestination, team_id: int, run_id: str) -> list[PolicyStatement]:
    if error := destination_error(destination):
        raise ApplicationError(error, non_retryable=True)
    statements = [
        PolicyStatement(
            Effect="Allow",
            Action=["s3:PutObject", "s3:AbortMultipartUpload"],
            # Only this run's folder, so the session cannot overwrite an earlier run's files.
            Resource=f"arn:aws:s3:::{destination.bucket}/{run_prefix(destination, team_id)}/{run_id}/*",
        )
    ]
    if destination.kms_key_id:
        # Completing a multipart upload decrypts each part's data key, so the role needs kms:Decrypt too.
        statements.append(
            PolicyStatement(
                Effect="Allow",
                Action=["kms:GenerateDataKey", "kms:Decrypt"],
                Resource=kms_key_arn(destination.kms_key_id, destination.region, destination.role_arn),
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
async def customer_bucket(team_id: int, destination: ExportDestination, run_id: str) -> AsyncIterator[CustomerBucket]:
    try:
        role = await resolve_s3_credentials(team_id, destination, run_id)
        async with s3_client(role.credentials, destination.region, refresh_using=role.refresh_using) as client:
            yield CustomerBucket(client, destination, role.owner_account_id)
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


class ByteBudget:
    """Caps the block bytes a shard holds in memory, across all its sessions."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.used = 0
        self.released = asyncio.Condition()

    def try_take(self, size: int) -> bool:
        # A block larger than the whole budget still goes through, alone.
        if self.used > 0 and self.used + size > self.capacity:
            return False
        self.used += size
        return True

    async def take(self, size: int) -> None:
        async with self.released:
            await self.released.wait_for(lambda: self.try_take(size))

    async def give_back(self, size: int) -> None:
        async with self.released:
            self.used -= size
            self.released.notify_all()


def block_size(block: Block) -> int:
    return block.end_byte - block.start_byte + 1


async def fetch_blocks_in_order(
    client: RecordingApiClient, session: SessionRow, team_id: int, budget: ByteBudget
) -> AsyncGenerator[bytes]:
    """Yield the session's blocks in order, with up to BLOCK_CONCURRENCY fetches in flight within the byte budget.

    A block's bytes stay reserved until the consumer asks for the next block, so they cover the write too.
    """
    pending: collections.deque[tuple[asyncio.Task[bytes], int]] = collections.deque()
    held = 0

    try:
        for block in session.blocks or []:
            size = block_size(block)
            # Drain this session's own queue before waiting, so sessions never wait on each other in a cycle.
            while pending and (len(pending) == BLOCK_CONCURRENCY or not budget.try_take(size)):
                task, held = pending.popleft()
                yield await task
                await budget.give_back(held)
                held = 0
            if not pending:
                await budget.take(size)
            pending.append((asyncio.create_task(fetch_block(client, block, session, team_id)), size))
        while pending:
            task, held = pending.popleft()
            yield await task
            await budget.give_back(held)
            held = 0
    finally:
        for task, _ in pending:
            task.cancel()
        await asyncio.gather(*(task for task, _ in pending), return_exceptions=True)
        await budget.give_back(held + sum(size for _, size in pending))


async def export_session(
    recordings: RecordingApiClient,
    bucket: CustomerBucket,
    budget: ByteBudget,
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
        async with contextlib.aclosing(fetch_blocks_in_order(recordings, session, input.team_id, budget)) as blocks:
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
async def check_destination(input: CheckDestinationInput) -> None:
    """Fails the run before any shard starts when the customer's role is unsafe or cannot write to the bucket."""
    if not settings.RECORDING_EXPORT_S3_EXTERNAL_ROLE_ARN:
        raise ApplicationError("RECORDING_EXPORT_S3_EXTERNAL_ROLE_ARN is not set on this worker", non_retryable=True)
    team = await Team.objects.aget(id=input.team_id)
    try:
        # Refuses a role that another organization could make us assume, because it lacks the external ID condition.
        await asyncio.to_thread(
            validate_aws_role_arn,
            input.destination.role_arn,
            settings.RECORDING_EXPORT_S3_EXTERNAL_ROLE_ARN,
            external_id(team.organization_id),
        )
    except IntegrationError as e:
        # Retryable, because the same error covers STS outages and a trust policy that IAM has not propagated yet.
        raise ApplicationError(str(e)) from e
    # A test upload that is aborted leaves no object, and each step needs a different permission.
    destination = input.destination
    key = f"{run_prefix(destination, input.team_id)}/{input.run_id}/preflight"
    create_needs = part_needs = f"s3:PutObject on s3://{destination.bucket}/{key}"
    if destination.kms_key_id:
        key_arn = kms_key_arn(destination.kms_key_id, destination.region, destination.role_arn)
        create_needs = f"{create_needs} and kms:GenerateDataKey on {key_arn}"
        part_needs = f"kms:Decrypt on {key_arn}"
    async with customer_bucket(input.team_id, destination, input.run_id) as bucket:
        upload_id = await _probe(bucket.create_multipart_upload(key), create_needs)
        try:
            await _probe(bucket.upload_part(key, upload_id, 1, bytearray(b"preflight")), part_needs)
        except BaseException:
            # The part's error names the permission at fault, so a failed abort must not replace it.
            with contextlib.suppress(Exception):
                await bucket.abort_multipart_upload(key, upload_id)
            raise
        await _probe(
            bucket.abort_multipart_upload(key, upload_id), f"s3:AbortMultipartUpload on s3://{destination.bucket}/{key}"
        )


async def _probe[T](call: Awaitable[T], permission: str) -> T:
    try:
        return await call
    except ClientError as e:
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 500)
        code = e.response.get("Error", {}).get("Code")
        if status >= 500 or status == 429 or code in TRANSIENT_S3_ERROR_CODES:
            raise
        if code == "AccessDenied":
            message = f"The role needs {permission}, in the AWS account that owns the bucket. AWS said: {e}"
        else:
            message = f"The bucket refused a test upload: {e}"
        raise ApplicationError(message, non_retryable=True) from e


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

    def load_page(listed: tuple[str, ...], after: str) -> asyncio.Task[tuple[list[SessionRow], SessionMetadata]]:
        def load() -> tuple[list[SessionRow], SessionMetadata]:
            sessions = list_shard_sessions(input, listed, after=after)
            return sessions, load_session_metadata(input.team_id, sessions, viewports) if sessions else ({}, {})

        return asyncio.create_task(database_sync_to_async_pool(load)())

    # Heartbeat from the start: the first listing can take minutes on a large day.
    async with Heartbeater(details=(checkpoint,)) as heartbeater:
        listed = await database_sync_to_async_pool(load_shard_session_ids)(
            input.session_ids_prefix, input.day, input.shard
        )
        # Pages load one after another in session ID order, so they read the file once, front to back.
        viewports = await database_sync_to_async_pool(ViewportReader.load)(
            input.team_id, input.run_id, input.day, input.shard
        )
        page = load_page(listed, checkpoint.last_session_id)
        try:
            async with (
                recording_api_client(connection_limit=RECORDING_API_CONNECTIONS) as recordings,
                customer_bucket(input.team_id, input.destination, input.run_id) as bucket,
            ):
                semaphore = asyncio.Semaphore(SESSION_CONCURRENCY)
                budget = ByteBudget(SHARD_BLOCK_BUFFER_BYTES)

                async def export_one(
                    session: SessionRow, viewports: list[dict[str, Any]], person: dict | None
                ) -> ManifestLine:
                    async with semaphore:
                        return await export_session(recordings, bucket, budget, input, session, viewports, person)

                prefix = manifest_prefix(input.destination, input.team_id, input.run_id)
                while True:
                    chunk, (page_viewports, persons) = await page
                    if not chunk:
                        break
                    # The next page lists and loads its metadata while this page exports.
                    page = load_page(listed, chunk[-1].session_id)
                    # A failed session cancels the rest of the page, and each cancelled session aborts its upload.
                    # Temporal then retries the shard from the last checkpoint.
                    try:
                        async with asyncio.TaskGroup() as group:
                            tasks = [
                                group.create_task(
                                    export_one(s, page_viewports.get(s.session_id, []), persons.get(s.distinct_id))
                                )
                                for s in chunk
                            ]
                    except ExceptionGroup as e:
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
        finally:
            # A failure anywhere, including a manifest write, must not leave the next page's queries running.
            page.cancel()
            await asyncio.gather(page, return_exceptions=True)

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
    async with customer_bucket(input.team_id, input.destination, input.run_id) as bucket:
        customer_quote = {key: quote[key] for key in CUSTOMER_QUOTE_FIELDS if key in quote}
        await bucket.put(f"{prefix}/quote.json", json.dumps(customer_quote, indent=2).encode())
        await bucket.put(f"{prefix}/summary.json", json.dumps(summary).encode())
