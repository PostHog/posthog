import re
import time
import queue
import base64
import hashlib
import datetime as dt
import threading
import contextvars
import dataclasses
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar
from functools import cache
from typing import Any, ClassVar, Literal

import orjson
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.loaders import Loader
from botocore.model import ServiceModel
from botocore.parsers import ResponseParserError, create_parser
from botocore.serialize import create_serializer
from structlog.types import FilteringBoundLogger
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    stop_before_delay,
    wait_exponential_jitter,
)

from products.warehouse_sources.sources.amazon_kinesis.settings import (
    ARRIVAL_TIMESTAMP_COLUMN,
    GET_RECORDS_INTERVAL_SECONDS,
    GET_RECORDS_LIMIT,
    INVALID_REGION_MESSAGE,
    KINESIS_API_VERSION,
    KPL_AGGREGATION_PREFIX,
    LIST_SHARDS_PAGE_SIZE,
    LIST_STREAMS_PAGE_SIZE,
    MAX_ATTEMPTS,
    NO_STREAMS_MESSAGE,
    PARTITION_KEY_COLUMN,
    PRIMARY_KEYS,
    RAW_DATA_COLUMN,
    RAW_DATA_ENCODING_COLUMN,
    REQUEST_TIMEOUT,
    RETRY_BUDGET_SECONDS,
    SEQUENCE_NUMBER_COLUMN,
    SHARD_ID_COLUMN,
    SHARD_QUEUE_POLL_SECONDS,
    SHARD_READ_WORKERS,
    STREAM_NOT_FOUND_MESSAGE,
    THROTTLING_ERROR_CODES,
    TRANSIENT_ERROR_CODES,
    UNREACHABLE_MESSAGE,
    VALIDATION_ERROR_MESSAGES,
    VALUE_COLUMN,
)
from products.warehouse_sources.sources.sdk import (
    NO_RETRY,
    ResumableSourceManager,
    SourceCursorManager,
    SourceResponse,
    frozen,
    interruptible_wait,
    make_tracked_session,
    reach_safe_point,
)
from products.warehouse_sources.sources.sdk.internals import NamingConvention

ERROR_PREFIX = "Amazon Kinesis request failed"

_REGION_ALPHABET = re.compile(r"[a-z0-9-]+")

_RESERVED_PAYLOAD_COLUMNS = frozenset(
    {
        SHARD_ID_COLUMN,
        SEQUENCE_NUMBER_COLUMN,
        PARTITION_KEY_COLUMN,
        ARRIVAL_TIMESTAMP_COLUMN,
        RAW_DATA_COLUMN,
        RAW_DATA_ENCODING_COLUMN,
        VALUE_COLUMN,
        "_ph_debug",
        "_ph_partition_key",
        "_dlt_id",
        "_dlt_load_id",
    }
)


@frozen
class KinesisCursor:
    cursor_kind: ClassVar[str] = "kinesis_sequence_numbers"

    positions: dict[str, str]
    finished_shards: list[str]
    stream_created_at: float


@frozen
class KinesisResumeState:
    started_at: float
    stream_created_at: float
    positions: dict[str, str]
    finished_shards: list[str]


class AmazonKinesisError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{ERROR_PREFIX}: {code} - {message}")
        self.code = code


class AmazonKinesisTransientError(AmazonKinesisError):
    pass


@cache
def _aws_partitions() -> list[dict[str, Any]]:
    return Loader().load_data("partitions")["partitions"]


# Not cached: the region comes from the setup form, so a cache keyed on it would grow without bound.
def aws_dns_suffix(region: str) -> str | None:
    if not _REGION_ALPHABET.fullmatch(region):
        return None
    for partition in _aws_partitions():
        if region in partition.get("regions", {}) or re.fullmatch(partition["regionRegex"], region):
            return partition["outputs"]["dnsSuffix"]
    return None


@cache
def _service_model() -> ServiceModel:
    return ServiceModel(
        Loader().load_service_model("kinesis", "service-2", api_version=KINESIS_API_VERSION), service_name="kinesis"
    )


def error_from(parsed: dict[str, Any], status_code: int) -> AmazonKinesisError:
    error = parsed.get("Error") or {}
    code = str(error.get("Code") or "").split("#")[-1]
    if not code or code.isdigit():
        code = f"HTTP {status_code}"
    message = str(error.get("Message") or "")[:500]
    if code in THROTTLING_ERROR_CODES or code in TRANSIENT_ERROR_CODES or status_code == 429 or status_code >= 500:
        return AmazonKinesisTransientError(code, message)
    return AmazonKinesisError(code, message)


# Set on the threads that read shards. Their rows have not reached the pipeline yet, so they never
# reach a safe point.
_on_shard_worker: ContextVar[bool] = ContextVar("kinesis_shard_worker", default=False)


def _before_retry_wait(_state: RetryCallState) -> None:
    if not _on_shard_worker.get():
        reach_safe_point()


def _retry_wait(seconds: float) -> None:
    interruptible_wait(seconds)


class KinesisClient:
    def __init__(self, access_key_id: str, secret_access_key: str, session_token: str | None, region: str) -> None:
        region = region.strip()
        suffix = aws_dns_suffix(region)
        if suffix is None:
            raise ValueError(INVALID_REGION_MESSAGE)
        model = _service_model()
        self._url = f"https://{model.endpoint_prefix}.{region}.{suffix}/"
        self._signer = SigV4Auth(
            Credentials(access_key_id.strip(), secret_access_key.strip(), session_token or None),
            model.signing_name,
            region,
        )
        self._session = make_tracked_session(
            retry=NO_RETRY,
            redact_values=tuple(value for value in (secret_access_key, session_token) if value),
            allow_redirects=False,
            capture=False,
        )

    @retry(
        retry=retry_if_exception_type(
            (
                AmazonKinesisTransientError,
                requests.ConnectionError,
                requests.Timeout,
                requests.exceptions.ChunkedEncodingError,
            )
        ),
        stop=stop_after_attempt(MAX_ATTEMPTS) | stop_before_delay(RETRY_BUDGET_SECONDS),
        wait=wait_exponential_jitter(initial=2, max=30),
        sleep=_retry_wait,
        before_sleep=_before_retry_wait,
        reraise=True,
    )
    def call(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        model = _service_model()
        operation_model = model.operation_model(operation)
        serialized = create_serializer(model.protocol, include_validation=False).serialize_to_request(
            params, operation_model
        )
        body = serialized["body"]
        if isinstance(body, str):
            body = body.encode()
        request = AWSRequest(method="POST", url=self._url, data=body, headers=dict(serialized["headers"]))
        self._signer.add_auth(request)
        response = self._session.post(
            self._url, data=body, headers=dict(request.headers.items()), timeout=REQUEST_TIMEOUT
        )
        output_shape = operation_model.output_shape
        assert output_shape is not None
        try:
            parsed = create_parser(model.protocol).parse(
                {"status_code": response.status_code, "headers": dict(response.headers), "body": response.content},
                output_shape,
            )
        except ResponseParserError:
            parsed = {"Error": {}} if response.status_code >= 400 else {"Error": {"Message": "unreadable response"}}
        if response.status_code >= 400 or "Error" in parsed:
            raise error_from(parsed, response.status_code)
        parsed.pop("ResponseMetadata", None)
        return parsed


def list_streams(client: KinesisClient) -> list[str]:
    names: list[str] = []
    params: dict[str, Any] = {"Limit": LIST_STREAMS_PAGE_SIZE}
    while True:
        page = client.call("ListStreams", params)
        names.extend(page.get("StreamNames") or [])
        token = page.get("NextToken")
        if not page.get("HasMoreStreams") or not token:
            return names
        params = {"Limit": LIST_STREAMS_PAGE_SIZE, "NextToken": token}


def list_shard_ids(client: KinesisClient, stream_name: str) -> list[str]:
    shard_ids: list[str] = []
    params: dict[str, Any] = {"StreamName": stream_name, "MaxResults": LIST_SHARDS_PAGE_SIZE}
    while True:
        page = client.call("ListShards", params)
        shard_ids.extend(shard["ShardId"] for shard in page.get("Shards") or [])
        token = page.get("NextToken")
        if not token:
            return sorted(shard_ids)
        params = {"NextToken": token, "MaxResults": LIST_SHARDS_PAGE_SIZE}


def validate_credentials(
    access_key_id: str,
    secret_access_key: str,
    session_token: str | None,
    region: str,
    stream_name: str | None,
) -> tuple[bool, str | None]:
    try:
        client = KinesisClient(access_key_id, secret_access_key, session_token, region)
    except ValueError:
        return False, INVALID_REGION_MESSAGE
    try:
        if stream_name is not None:
            client.call("DescribeStreamSummary", {"StreamName": stream_name})
        elif not client.call("ListStreams", {"Limit": 1}).get("StreamNames"):
            return False, NO_STREAMS_MESSAGE
    except AmazonKinesisTransientError:
        return False, UNREACHABLE_MESSAGE
    except AmazonKinesisError as error:
        if stream_name is not None and error.code == "ResourceNotFoundException":
            return False, STREAM_NOT_FOUND_MESSAGE
        return False, VALIDATION_ERROR_MESSAGES.get(error.code, f"AWS rejected the request: {error.code}.")
    except requests.RequestException:
        return False, UNREACHABLE_MESSAGE
    return True, None


@frozen
class _RawPayload:
    value: str
    encoding: Literal["utf-8", "base64"]

    def columns(self) -> dict[str, str]:
        return {RAW_DATA_COLUMN: self.value, RAW_DATA_ENCODING_COLUMN: self.encoding}


def _base64_payload(data: bytes) -> _RawPayload:
    return _RawPayload(value=base64.b64encode(data).decode("ascii"), encoding="base64")


def _raw_payload(data: bytes) -> _RawPayload:
    try:
        return _RawPayload(value=data.decode("utf-8"), encoding="utf-8")
    except UnicodeDecodeError:
        return _base64_payload(data)


def _normalize_payload_key(name: str) -> str:
    try:
        return NamingConvention.normalize_identifier(name)
    except ValueError:
        return "column"


def _hashed_payload_column_name(name: str, normalized: str) -> str:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"_kinesis_payload_{normalized}_{digest}"


def _payload_columns(payload: dict[str, Any]) -> dict[str, Any]:
    """Map JSON keys to snake_case columns, renaming only keys that would clash.

    A key is hashed into an opaque `_kinesis_payload_*` column only when its normalized name is reserved,
    uses the `_kinesis_` prefix, or collides with another key of the same record (e.g. `userId` and `user_id`;
    the key already in snake_case keeps the plain name).
    """
    normalized_keys = {key: _normalize_payload_key(key) for key in payload}
    owners: dict[str, str] = {}
    for key, normalized in normalized_keys.items():
        if normalized in _RESERVED_PAYLOAD_COLUMNS or normalized.startswith("_kinesis_"):
            continue
        current = owners.get(normalized)
        if current is None or (key == normalized and current != normalized):
            owners[normalized] = key
    columns: dict[str, Any] = {}
    for key, value in payload.items():
        normalized = normalized_keys[key]
        if owners.get(normalized) == key:
            columns[normalized] = value
        else:
            columns[_hashed_payload_column_name(key, normalized)] = value
    return columns


def record_to_row(record: dict[str, Any], shard_id: str) -> dict[str, Any]:
    data: bytes = record["Data"]
    row: dict[str, Any] = {}
    if data.startswith(KPL_AGGREGATION_PREFIX):
        row.update(_base64_payload(data).columns())
    else:
        try:
            decoded = orjson.loads(data)
        except orjson.JSONDecodeError:
            row.update(_raw_payload(data).columns())
        else:
            if isinstance(decoded, dict):
                row.update(_payload_columns(decoded))
            else:
                row[VALUE_COLUMN] = orjson.dumps(decoded).decode()
    row.update(
        {
            SHARD_ID_COLUMN: shard_id,
            SEQUENCE_NUMBER_COLUMN: record["SequenceNumber"],
            PARTITION_KEY_COLUMN: record.get("PartitionKey"),
            ARRIVAL_TIMESTAMP_COLUMN: record["ApproximateArrivalTimestamp"].astimezone(dt.UTC),
        }
    )
    return row


class _ShardExpiredError(Exception):
    pass


def _raise_if_shard_expired(
    client: KinesisClient, stream_name: str, shard_id: str, error: AmazonKinesisError, logger: FilteringBoundLogger
) -> None:
    if error.code != "ResourceNotFoundException":
        return
    # Kinesis answers the same way for a shard that retention removed and for a deleted stream. A
    # deleted stream fails here and keeps its error, so only a missing shard is skipped.
    client.call("DescribeStreamSummary", {"StreamName": stream_name})
    logger.warning("Kinesis retention removed a shard while this table was reading the stream", shard_id=shard_id)
    raise _ShardExpiredError(shard_id) from error


def _shard_iterator(
    client: KinesisClient, stream_name: str, shard_id: str, after: str | None, logger: FilteringBoundLogger
) -> str | None:
    params: dict[str, Any] = {"StreamName": stream_name, "ShardId": shard_id, "ShardIteratorType": "TRIM_HORIZON"}
    try:
        if after is not None:
            try:
                return client.call(
                    "GetShardIterator",
                    {**params, "ShardIteratorType": "AFTER_SEQUENCE_NUMBER", "StartingSequenceNumber": after},
                ).get("ShardIterator")
            except AmazonKinesisError as error:
                if error.code != "InvalidArgumentException":
                    raise
                logger.warning(
                    "Kinesis rejected the stored position of a shard, reading the shard from its oldest record",
                    shard_id=shard_id,
                )
        return client.call("GetShardIterator", params).get("ShardIterator")
    except AmazonKinesisError as error:
        _raise_if_shard_expired(client, stream_name, shard_id, error, logger)
        raise


@frozen(frozen=False)
class _ReadProgress:
    started_at: float
    stream_created_at: float
    positions: dict[str, str]
    finished: set[str]

    def advance(self, shard_id: str, sequence: str | None) -> None:
        if sequence is not None:
            self.positions[shard_id] = sequence

    def resume_state(self) -> KinesisResumeState:
        return KinesisResumeState(
            started_at=self.started_at,
            stream_created_at=self.stream_created_at,
            positions=dict(self.positions),
            finished_shards=sorted(self.finished),
        )

    def cursor(self) -> KinesisCursor:
        return KinesisCursor(
            positions=dict(self.positions),
            finished_shards=sorted(self.finished),
            stream_created_at=self.stream_created_at,
        )


@frozen
class _PageRows:
    rows: list[dict[str, Any]]
    last_sequence: str | None
    reached_run_end: bool
    aggregated: int


def _rows_before(records: list[dict[str, Any]], shard_id: str, started_at: float) -> _PageRows:
    rows: list[dict[str, Any]] = []
    last_sequence: str | None = None
    aggregated = 0
    for record in records:
        if record["ApproximateArrivalTimestamp"].timestamp() >= started_at:
            return _PageRows(rows=rows, last_sequence=last_sequence, reached_run_end=True, aggregated=aggregated)
        rows.append(record_to_row(record, shard_id))
        aggregated += record["Data"].startswith(KPL_AGGREGATION_PREFIX)
        last_sequence = record["SequenceNumber"]
    return _PageRows(rows=rows, last_sequence=last_sequence, reached_run_end=False, aggregated=aggregated)


@frozen
class _ShardPage:
    shard_id: str
    rows: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    last_sequence: str | None = None
    # The shard is closed and every record of it has been read.
    finished: bool = False
    # Retention removed the shard, so its position no longer means anything.
    expired: bool = False
    # The worker reads no more pages of this shard in this run.
    done: bool = False
    aggregated: int = 0
    error: BaseException | None = None


def _fetch_shard(
    client: KinesisClient,
    stream_name: str,
    shard_id: str,
    after: str | None,
    started_at: float,
    stop: threading.Event,
    logger: FilteringBoundLogger,
) -> Iterator[_ShardPage]:
    """Read the pages of one shard on a pool thread, up to the start of the run."""
    position = after
    try:
        iterator = _shard_iterator(client, stream_name, shard_id, position, logger)
        last_request: float | None = None
        while iterator is not None and not stop.is_set():
            if last_request is not None:
                # No safe point here: the rows of this thread have not reached the pipeline yet.
                interruptible_wait(max(0.0, GET_RECORDS_INTERVAL_SECONDS - (time.monotonic() - last_request)))
                if stop.is_set():
                    return
            last_request = time.monotonic()
            try:
                page = client.call("GetRecords", {"ShardIterator": iterator, "Limit": GET_RECORDS_LIMIT})
            except AmazonKinesisError as error:
                _raise_if_shard_expired(client, stream_name, shard_id, error, logger)
                if error.code != "ExpiredIteratorException":
                    raise
                iterator = _shard_iterator(client, stream_name, shard_id, position, logger)
                continue

            read = _rows_before(page.get("Records") or [], shard_id, started_at)
            if read.last_sequence is not None:
                position = read.last_sequence
            iterator = page.get("NextShardIterator")
            yield _ShardPage(
                shard_id=shard_id,
                rows=read.rows,
                last_sequence=read.last_sequence,
                finished=iterator is None and not read.reached_run_end,
                aggregated=read.aggregated,
            )
            if read.reached_run_end or page.get("MillisBehindLatest") == 0:
                return
    except _ShardExpiredError:
        yield _ShardPage(shard_id=shard_id, expired=True)


def _next_page(
    pages: "queue.Queue[_ShardPage]",
    tasks: list[Future[None]],
    resumable_source_manager: ResumableSourceManager[KinesisResumeState],
) -> _ShardPage:
    while True:
        try:
            return pages.get(timeout=SHARD_QUEUE_POLL_SECONDS)
        except queue.Empty:
            for task in tasks:
                error = task.exception() if task.done() else None
                if error is not None:
                    raise error
            # Every row the staged state covers has been yielded, and the rows the workers hold are
            # past it, so the run can stop here and resume from the staged state.
            resumable_source_manager.safe_point()


def read_stream(
    client: KinesisClient,
    stream_name: str,
    start: KinesisResumeState,
    resumable_source_manager: ResumableSourceManager[KinesisResumeState],
    cursor_manager: SourceCursorManager[KinesisCursor],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    shard_ids = list_shard_ids(client, stream_name)
    live = set(shard_ids)
    expired = sorted(set(start.positions) - live - set(start.finished_shards))
    if expired:
        logger.warning("Kinesis retention removed shards before this table finished reading them", shard_ids=expired)
    progress = _ReadProgress(
        started_at=start.started_at,
        stream_created_at=start.stream_created_at,
        positions={shard_id: sequence for shard_id, sequence in start.positions.items() if shard_id in live},
        finished=set(start.finished_shards) & live,
    )

    pages: queue.Queue[_ShardPage] = queue.Queue(maxsize=SHARD_READ_WORKERS)
    stop = threading.Event()

    def hand_over(page: _ShardPage) -> None:
        while not stop.is_set():
            try:
                pages.put(page, timeout=SHARD_QUEUE_POLL_SECONDS)
                return
            except queue.Full:
                continue

    def read(shard_id: str, after: str | None) -> None:
        _on_shard_worker.set(True)
        try:
            for page in _fetch_shard(client, stream_name, shard_id, after, progress.started_at, stop, logger):
                hand_over(page)
            hand_over(_ShardPage(shard_id=shard_id, done=True))
        except BaseException as error:
            hand_over(_ShardPage(shard_id=shard_id, done=True, error=error))

    pending = [shard_id for shard_id in shard_ids if shard_id not in progress.finished]
    active: set[str] = set()
    tasks: list[Future[None]] = []
    aggregated = 0
    executor = ThreadPoolExecutor(max_workers=SHARD_READ_WORKERS, thread_name_prefix="kinesis-shard")
    try:
        while pending or active:
            while pending and len(active) < SHARD_READ_WORKERS:
                shard_id = pending.pop(0)
                active.add(shard_id)
                # A copy of the context keeps the job's log, request tracking and shutdown signal in the worker.
                tasks.append(
                    executor.submit(contextvars.copy_context().run, read, shard_id, progress.positions.get(shard_id))
                )
            page = _next_page(pages, tasks, resumable_source_manager)
            if page.error is not None:
                raise page.error
            if page.done:
                active.discard(page.shard_id)
                continue
            if page.expired:
                progress.positions.pop(page.shard_id, None)
                progress.finished.discard(page.shard_id)
            else:
                aggregated += page.aggregated
                progress.advance(page.shard_id, page.last_sequence)
                if page.finished:
                    progress.finished.add(page.shard_id)
            resumable_source_manager.save_state(progress.resume_state())
            cursor_manager.stage(progress.cursor())
            if page.rows:
                yield page.rows
            else:
                resumable_source_manager.safe_point()
    finally:
        stop.set()
        while not pages.empty():
            pages.get_nowait()
        executor.shutdown(wait=False, cancel_futures=True)

    if aggregated:
        logger.warning(
            "Kinesis records aggregated by the Kinesis Producer Library were stored without unpacking",
            records=aggregated,
        )
    cursor_manager.stage(progress.cursor())


def amazon_kinesis_source(
    client: KinesisClient,
    stream_name: str,
    resumable_source_manager: ResumableSourceManager[KinesisResumeState],
    cursor_manager: SourceCursorManager[KinesisCursor],
    use_cursor: bool,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    summary = client.call("DescribeStreamSummary", {"StreamName": stream_name})["StreamDescriptionSummary"]
    created_at = summary["StreamCreationTimestamp"].timestamp()
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    stored = cursor_manager.load() if use_cursor else None
    recreated = stored is not None and stored.stream_created_at != created_at

    if resume is not None and resume.stream_created_at == created_at:
        start = resume
        recreated = False
    else:
        if resume is not None:
            # The saved state belongs to the deleted stream. Left in place, the pipeline would treat
            # this run as a resume and keep the rows of the old stream.
            resumable_source_manager.clear_state()
            recreated = True
        if recreated:
            logger.warning("Kinesis stream was deleted and created again, rebuilding the table from the new stream")
        kept = stored if stored is not None and not recreated else None
        start = KinesisResumeState(
            started_at=dt.datetime.now(dt.UTC).timestamp(),
            stream_created_at=created_at,
            positions=dict(kept.positions) if kept else {},
            finished_shards=list(kept.finished_shards) if kept else [],
        )

    return SourceResponse(
        name=stream_name,
        items=lambda: read_stream(client, stream_name, start, resumable_source_manager, cursor_manager, logger),
        primary_keys=PRIMARY_KEYS,
        partition_mode="datetime",
        partition_keys=[ARRIVAL_TIMESTAMP_COLUMN],
        sort_mode=None,
        destination_reset_required=recreated,
        # Clear the checkpoint only once the pipeline has written every batch, so a crash before then resumes.
        on_complete=resumable_source_manager.clear_state,
    )
