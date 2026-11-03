import re
import json
import decimal
import datetime as dt
import tempfile
import dataclasses
import email.utils
from collections.abc import Callable, Iterator
from functools import cache
from typing import IO, Any, Optional
from urllib.parse import quote, urlencode

import orjson
import pyarrow as pa
import requests
import pyarrow.parquet as pq
from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.loaders import Loader
from defusedxml import ElementTree
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    normalize_column_name as pipeline_column_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_and_usage_report.settings import (
    BILLING_PERIOD_DIRECTORY,
    BILLING_PERIOD_INPUT,
    BUCKET_NAME,
    COST_AND_USAGE,
    DATA_FILE_SUFFIXES,
    DECIMAL_TYPE,
    DOWNLOAD_CHUNK_BYTES,
    LIST_PAGE_SIZE,
    ROWS_PER_BATCH,
    S3_NAMESPACE,
    S3_SIGNING_NAME,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.file_parsing import (
    iter_file_rows,
    normalize_column_name,
    resolve_file_format,
    uses_brotli_compression,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import reach_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

REQUEST_TIMEOUT_SECONDS = 120
# A dropped connection mid-body escapes the transport's retry, which only covers the response
# headers. One file is retried on its own so a late failure does not restart the whole refresh.
DOWNLOAD_ATTEMPTS = 3
NO_MANIFEST = "NoManifest"
DELIVERY_IN_PROGRESS = "DeliveryInProgress"
MANIFEST_UNREADABLE = "ManifestUnreadable"
UNSUPPORTED_COMPRESSION = "UnsupportedCompression"
BILLING_PERIOD_COLUMN = "billing_period"
ERROR_PREFIX = "AWS Cost and Usage Report request failed"
WRONG_REGION_CODES = frozenset(
    {"PermanentRedirect", "AuthorizationHeaderMalformed", "IllegalLocationConstraintException"}
)


class AwsCostAndUsageReportError(Exception):
    def __init__(self, message: str, code: str | None = None, bucket_region: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.bucket_region = bucket_region


@dataclasses.dataclass(frozen=True)
class S3ListPage:
    keys: list[str]
    prefixes: list[str]
    next_token: Optional[str]


@dataclasses.dataclass(frozen=True)
class Delivery:
    """The latest complete delivery of one billing period, as its manifest describes it."""

    keys: list[str]
    # Column name -> the type the export declares for it, lowercased.
    column_types: dict[str, str]
    # When AWS wrote the manifest. An "overwrite" export rewrites its data files in place, so a
    # file changed after this belongs to a newer delivery.
    manifest_last_modified: Optional[str] = None


@frozen
class CostAndUsageReportResumeConfig:
    """How far a full refresh got: the billing period, the delivery it read, and the next batch.

    `manifest_last_modified` pins the delivery. If AWS delivered the period again since, the saved
    file and batch numbers point into a different set of files.
    """

    billing_period: str
    manifest_last_modified: Optional[str]
    file_index: int
    batch_index: int


@dataclasses.dataclass(frozen=True)
class S3Body:
    content: bytes
    last_modified: Optional[str]


@cache
def aws_dns_suffix(region: str) -> Optional[str]:
    """The DNS suffix of the AWS partition a region belongs to, or None for an unknown region.

    China regions live under `amazonaws.com.cn`, so the suffix comes from botocore's partition table.
    """
    for partition in Loader().load_data("partitions")["partitions"]:
        if region in partition.get("regions", {}) or re.match(partition["regionRegex"], region):
            return partition["outputs"]["dnsSuffix"]
    return None


def export_base(prefix: Optional[str], export_name: str) -> str:
    """`<prefix>/<export-name>`, the directory Data Exports writes `data/` and `metadata/` under."""
    parts = [part.strip("/") for part in (prefix or "", export_name) if part and part.strip("/")]
    return "/".join(parts)


def parse_billing_period(value: Optional[str]) -> Optional[dt.date]:
    if not value or not value.strip():
        return None
    value = value.strip()
    if not BILLING_PERIOD_INPUT.match(value):
        raise ValueError("Enter the first billing period as YYYY-MM, for example 2024-01.")
    year, month = value.split("-")
    return dt.date(int(year), int(month), 1)


def error_for_response(response: requests.Response) -> AwsCostAndUsageReportError:
    code = f"HTTP {response.status_code}"
    message = ""
    if response.content:
        try:
            root = ElementTree.fromstring(response.content)
            code = root.findtext("Code") or code
            message = (root.findtext("Message") or "")[:500]
        except ElementTree.ParseError:
            message = response.text[:500]
    region = response.headers.get("x-amz-bucket-region")
    return AwsCostAndUsageReportError(f"{ERROR_PREFIX}: {code} - {message}", code, region)


def parse_list_page(body: bytes) -> S3ListPage:
    root = ElementTree.fromstring(body)
    keys = [item.findtext(f"{S3_NAMESPACE}Key") or "" for item in root.findall(f"{S3_NAMESPACE}Contents")]
    prefixes = [item.findtext(f"{S3_NAMESPACE}Prefix") or "" for item in root.findall(f"{S3_NAMESPACE}CommonPrefixes")]
    truncated = (root.findtext(f"{S3_NAMESPACE}IsTruncated") or "").lower() == "true"
    next_token = root.findtext(f"{S3_NAMESPACE}NextContinuationToken") if truncated else None
    return S3ListPage(keys=keys, prefixes=[prefix for prefix in prefixes if prefix], next_token=next_token)


class S3Client:
    """Reads one bucket with SigV4-signed GETs over the tracked session."""

    def __init__(
        self,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        aws_session_token: Optional[str],
        aws_region: str,
        bucket: str,
    ) -> None:
        redact = tuple(value for value in (aws_secret_access_key, aws_session_token) if value)
        self._session = make_tracked_session(redact_values=redact, allow_redirects=False)
        # Data files run to hundreds of megabytes, so they stay out of the sampled request capture.
        self._download_session = make_tracked_session(redact_values=redact, allow_redirects=False, capture=False)
        self._credentials = Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None)
        self._region = aws_region.strip()
        self._bucket = bucket.strip()

    def _url(self, key: str = "", query: Optional[dict[str, str]] = None) -> str:
        path = quote(key, safe="/~")
        suffix = aws_dns_suffix(self._region) or "amazonaws.com"
        # A bucket name with a dot breaks the TLS wildcard on the virtual-hosted name.
        if "." in self._bucket:
            url = f"https://s3.{self._region}.{suffix}/{self._bucket}/{path}"
        else:
            url = f"https://{self._bucket}.s3.{self._region}.{suffix}/{path}"
        if query:
            url = f"{url}?{urlencode(sorted(query.items()), quote_via=quote, safe='~')}"
        return url

    def _signed_headers(self, url: str, extra_headers: Optional[dict[str, str]] = None) -> dict[str, str]:
        aws_request = AWSRequest(method="GET", url=url, headers=dict(extra_headers or {}))
        S3SigV4Auth(self._credentials, S3_SIGNING_NAME, self._region).add_auth(aws_request)
        return dict(aws_request.headers.items())

    def _get(
        self,
        session: requests.Session,
        url: str,
        stream: bool = False,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> requests.Response:
        response = session.get(
            url,
            headers=self._signed_headers(url, extra_headers),
            timeout=REQUEST_TIMEOUT_SECONDS,
            stream=stream,
            allow_redirects=False,
        )
        if response.status_code >= 300:
            raise error_for_response(response)
        return response

    def list_page(
        self, prefix: str, continuation_token: Optional[str] = None, max_keys: int = LIST_PAGE_SIZE
    ) -> S3ListPage:
        query = {"list-type": "2", "prefix": prefix, "delimiter": "/", "max-keys": str(max_keys)}
        if continuation_token:
            query["continuation-token"] = continuation_token
        return parse_list_page(self._get(self._session, self._url(query=query)).content)

    def list_all(self, prefix: str) -> S3ListPage:
        keys: list[str] = []
        prefixes: list[str] = []
        token: Optional[str] = None
        while True:
            page = self.list_page(prefix, token)
            keys.extend(page.keys)
            prefixes.extend(page.prefixes)
            token = page.next_token
            reach_safe_point()
            if not token:
                return S3ListPage(keys=keys, prefixes=prefixes, next_token=None)

    def get_object(self, key: str) -> Optional[S3Body]:
        """The object body and its `Last-Modified`, or None when the key does not exist."""
        try:
            response = self._get(self._session, self._url(key))
            return S3Body(content=response.content, last_modified=response.headers.get("Last-Modified"))
        except AwsCostAndUsageReportError as error:
            if error.code in ("NoSuchKey", "HTTP 404"):
                return None
            raise

    def download(self, key: str, destination: IO[bytes], unmodified_since: Optional[str] = None) -> None:
        conditions = {"If-Unmodified-Since": unmodified_since} if unmodified_since else None
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            destination.seek(0)
            destination.truncate()
            try:
                with self._get(
                    self._download_session, self._url(key), stream=True, extra_headers=conditions
                ) as response:
                    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                        destination.write(chunk)
                break
            except (
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ):
                if attempt == DOWNLOAD_ATTEMPTS:
                    raise
                interruptible_wait(2**attempt)
        destination.flush()
        destination.seek(0)


def list_billing_periods(client: S3Client, base: str, first_period: Optional[dt.date]) -> list[dt.date]:
    periods: set[dt.date] = set()
    for prefix in client.list_all(f"{base}/data/").prefixes:
        match = BILLING_PERIOD_DIRECTORY.search(prefix)
        if match:
            periods.add(dt.date(int(match.group(1)), int(match.group(2)), 1))
    return sorted(period for period in periods if first_period is None or period >= first_period)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def manifest_data_keys(manifest: Any, bucket: str) -> list[str]:
    """The data files a manifest lists.

    AWS documents what a manifest holds but not its field names, so every string that names a
    data file counts, as an `s3://` URI in this bucket or as a bare key.
    """
    keys: list[str] = []
    for value in _strings(manifest):
        if not value.endswith(DATA_FILE_SUFFIXES):
            continue
        if value.startswith("s3://"):
            value_bucket, _, key = value[len("s3://") :].partition("/")
            if value_bucket != bucket:
                continue
            value = key
        keys.append(value)
    return list(dict.fromkeys(keys))


def manifest_column_types(manifest: Any) -> dict[str, str]:
    """The column types a manifest declares, from every object that carries a name and a type."""
    types: dict[str, str] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            fields = {str(key).lower(): item for key, item in value.items()}
            name, kind = fields.get("name"), fields.get("type")
            if isinstance(name, str) and isinstance(kind, str):
                types[name] = kind.lower()
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(manifest)
    return types


def latest_delivery(client: S3Client, bucket: str, base: str, export_name: str, period: dt.date) -> Optional[Delivery]:
    """The latest complete delivery of one billing period, or None while it has no manifest.

    AWS writes the manifest only after every data file of a delivery has landed, so a partition
    without one is still being delivered and its files would be incomplete.
    """
    partition = f"BILLING_PERIOD={period:%Y-%m}"
    # An "overwrite" export writes `<export>-Manifest.json` and a "create new" one `Manifest.json`.
    # An export switched between the two leaves the old one behind, so the newer one wins.
    found: list[tuple[dt.datetime, str, S3Body]] = []
    for manifest_key in (
        f"{base}/metadata/{partition}/{export_name.strip('/')}-Manifest.json",
        f"{base}/metadata/{partition}/Manifest.json",
    ):
        manifest_object = client.get_object(manifest_key)
        reach_safe_point()
        if manifest_object is not None:
            found.append((_http_date(manifest_object.last_modified), manifest_key, manifest_object))
    if not found:
        return None
    _, manifest_key, manifest_object = max(found, key=lambda item: item[0])
    unreadable = AwsCostAndUsageReportError(
        f"{ERROR_PREFIX}: {MANIFEST_UNREADABLE} - s3://{bucket}/{manifest_key} lists no data files",
        MANIFEST_UNREADABLE,
    )
    try:
        manifest = json.loads(manifest_object.content)
    except ValueError as error:
        raise unreadable from error
    keys = manifest_data_keys(manifest, bucket)
    if not keys:
        raise unreadable
    return Delivery(
        keys=keys,
        column_types=manifest_column_types(manifest),
        manifest_last_modified=manifest_object.last_modified,
    )


def _http_date(value: Optional[str]) -> dt.datetime:
    try:
        return email.utils.parsedate_to_datetime(value) if value else dt.datetime.min.replace(tzinfo=dt.UTC)
    except (TypeError, ValueError):
        return dt.datetime.min.replace(tzinfo=dt.UTC)


def _jsonable(value: Any, value_type: pa.DataType) -> Any:
    if value is None:
        return None
    if pa.types.is_map(value_type):
        return {str(key): _jsonable(item, value_type.item_type) for key, item in value}
    if pa.types.is_struct(value_type):
        return {field.name: _jsonable(value.get(field.name), field.type) for field in value_type}
    if pa.types.is_list(value_type) or pa.types.is_large_list(value_type):
        return [_jsonable(item, value_type.value_type) for item in value]
    return value


def _is_nested(value_type: pa.DataType) -> bool:
    return (
        pa.types.is_map(value_type)
        or pa.types.is_struct(value_type)
        or pa.types.is_list(value_type)
        or pa.types.is_large_list(value_type)
    )


def shape_table(table: pa.Table, period: dt.date) -> pa.Table:
    """JSON-encode nested columns (`resource_tags`, `product`, `cost_category`, ...) and add the billing period."""
    for index, field in enumerate(table.schema):
        if _is_nested(field.type):
            encoded = [
                None if value is None else orjson.dumps(_jsonable(value, field.type), default=str).decode()
                for value in table.column(index).to_pylist()
            ]
            table = table.set_column(index, field.name, pa.array(encoded, type=pa.string()))

    period_start = dt.datetime(period.year, period.month, 1, tzinfo=dt.UTC)
    column = pa.array([period_start] * table.num_rows, type=pa.timestamp("us", tz="UTC"))
    existing = table.schema.get_field_index(BILLING_PERIOD_COLUMN)
    if existing >= 0:
        return table.set_column(existing, BILLING_PERIOD_COLUMN, column)
    return table.append_column(BILLING_PERIOD_COLUMN, column)


def _parse_timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)


def _parse_boolean(value: str) -> bool:
    return value.strip().lower() == "true"


@dataclasses.dataclass(frozen=True)
class CsvColumnType:
    convert: Callable[[str], Any]
    arrow_type: pa.DataType


def csv_column_type(declared_type: str) -> Optional[CsvColumnType]:
    """How to read a CSV cell of a declared column type, and the Arrow type it lands as. None keeps the text."""
    if declared_type in ("double", "float", "real"):
        return CsvColumnType(float, pa.float64())
    if match := DECIMAL_TYPE.match(declared_type):
        # Same type as the Parquet file of the same export, so a format switch keeps the column type.
        precision, scale = int(match.group(1)), int(match.group(2))
        step = decimal.Decimal(1).scaleb(-scale)
        # The default context holds 28 digits, which a decimal(38, 30) value can exceed.
        context = decimal.Context(prec=precision)
        return CsvColumnType(
            lambda text: decimal.Decimal(text).quantize(step, context=context), pa.decimal128(precision, scale)
        )
    if declared_type.startswith("decimal"):
        return CsvColumnType(float, pa.float64())
    if declared_type in ("bigint", "int", "integer", "smallint", "tinyint", "long"):
        return CsvColumnType(int, pa.int64())
    if declared_type.startswith("timestamp") or declared_type == "datetime":
        return CsvColumnType(_parse_timestamp, pa.timestamp("us", tz="UTC"))
    if declared_type == "date":
        return CsvColumnType(dt.date.fromisoformat, pa.date32())
    if declared_type in ("boolean", "bool"):
        return CsvColumnType(_parse_boolean, pa.bool_())
    return None


def convert_csv_rows(rows: list[dict[str, Any]], converters: dict[str, Callable[[str], Any]]) -> int:
    """Give CSV cells the types the export declares. Every cell arrives as text, so without this a
    cost column would land as a string. An empty or unreadable cell becomes null.

    Returns how many non-empty cells could not be read."""
    unreadable = 0
    for row in rows:
        for column, convert in converters.items():
            value = row.get(column)
            if value is None:
                continue
            if value == "":
                row[column] = None
                continue
            try:
                row[column] = convert(value)
            except (TypeError, ValueError, ArithmeticError):
                row[column] = None
                unreadable += 1
    return unreadable


def iter_data_file(
    client: S3Client, key: str, period: dt.date, delivery: Delivery, logger: FilteringBoundLogger
) -> Iterator[pa.Table]:
    """Yield the file's rows as Arrow tables, whatever its format, so one run never mixes item types."""
    with tempfile.NamedTemporaryFile(suffix=".download") as destination:
        try:
            client.download(key, destination, unmodified_since=delivery.manifest_last_modified)
        except AwsCostAndUsageReportError as error:
            if error.code != "PreconditionFailed":
                raise
            raise AwsCostAndUsageReportError(
                f"{ERROR_PREFIX}: {DELIVERY_IN_PROGRESS} - AWS is rewriting billing period {period:%Y-%m}; "
                "the next attempt reads its finished delivery",
                DELIVERY_IN_PROGRESS,
            ) from error
        if key.endswith(".parquet"):
            parquet_file = pq.ParquetFile(destination)
            if uses_brotli_compression(parquet_file.metadata):
                raise AwsCostAndUsageReportError(
                    f"{ERROR_PREFIX}: {UNSUPPORTED_COMPRESSION} - {key} uses Brotli compression, which PostHog can't read",
                    UNSUPPORTED_COMPRESSION,
                )
            for batch in parquet_file.iter_batches(batch_size=ROWS_PER_BATCH):
                table = pa.Table.from_batches([batch])
                if table.num_rows:
                    yield shape_table(table, period)
            return

        period_start = dt.datetime(period.year, period.month, 1, tzinfo=dt.UTC)
        # The CSV reader lowercases headers (`BilledCost` becomes `billedcost`), but the pipeline
        # snake-cases Parquet columns (`billed_cost`). The manifest keeps the original names, so CSV
        # columns take the Parquet name and an export that changes format keeps one column per measure.
        column_names = {normalize_column_name(name): pipeline_column_name(name) for name in delivery.column_types}
        column_types = {
            pipeline_column_name(name): column_type
            for name, kind in delivery.column_types.items()
            if (column_type := csv_column_type(kind)) is not None
        }
        converters = {name: column_type.convert for name, column_type in column_types.items()}
        unreadable = 0
        for file_rows in iter_file_rows(
            destination, resolve_file_format(key), key, chunk_size=ROWS_PER_BATCH, logger=logger
        ):
            if not file_rows:
                continue
            rows = [{column_names.get(name, name): value for name, value in row.items()} for row in file_rows]
            unreadable += convert_csv_rows(rows, converters)
            for row in rows:
                row[BILLING_PERIOD_COLUMN] = period_start
            schema = pa.schema(
                [
                    pa.field(
                        name,
                        pa.timestamp("us", tz="UTC")
                        if name == BILLING_PERIOD_COLUMN
                        else (column_types[name].arrow_type if name in column_types else pa.string()),
                    )
                    for name in rows[0]
                ]
            )
            yield pa.Table.from_pylist(rows, schema=schema)
        if unreadable:
            logger.warning(
                f"{unreadable} cell(s) in {key} did not match the type the manifest declares and were set to null"
            )


def get_rows(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    aws_region: str,
    bucket: str,
    prefix: Optional[str],
    export_name: str,
    first_billing_period: Optional[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CostAndUsageReportResumeConfig],
) -> Iterator[pa.Table]:
    client = S3Client(aws_access_key_id, aws_secret_access_key, aws_session_token, aws_region, bucket)
    base = export_base(prefix, export_name)
    periods = list_billing_periods(client, base, parse_billing_period(first_billing_period))
    if not periods:
        logger.warning(f"No billing periods found under s3://{bucket.strip()}/{base}/data/")
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    delivered = 1 if resume is not None else 0
    for period in periods:
        billing_period = f"{period:%Y-%m}"
        if resume is not None and billing_period < resume.billing_period:
            continue
        delivery = latest_delivery(client, bucket.strip(), base, export_name, period)
        if delivery is None:
            logger.warning(f"Skipping billing period {billing_period}: AWS has not finished delivering it")
            continue
        first_file, first_batch = 0, 0
        if resume is not None and billing_period == resume.billing_period:
            if delivery.manifest_last_modified != resume.manifest_last_modified:
                # The rows already read came from the older delivery, so only a fresh refresh is consistent.
                resumable_source_manager.clear_state()
                raise AwsCostAndUsageReportError(
                    f"{ERROR_PREFIX}: {DELIVERY_IN_PROGRESS} - AWS delivered billing period {billing_period} "
                    "again during this sync; the next attempt starts over",
                    DELIVERY_IN_PROGRESS,
                )
            first_file, first_batch = resume.file_index, resume.batch_index
        else:
            delivered += 1
        logger.debug(f"Reading billing period {billing_period} from {len(delivery.keys)} file(s)")
        for file_index, key in enumerate(delivery.keys):
            if file_index < first_file:
                continue
            skip = first_batch if file_index == first_file else 0
            for batch_index, table in enumerate(iter_data_file(client, key, period, delivery, logger)):
                if batch_index < skip:
                    continue
                resumable_source_manager.save_state(
                    CostAndUsageReportResumeConfig(
                        billing_period=billing_period,
                        manifest_last_modified=delivery.manifest_last_modified,
                        file_index=file_index,
                        batch_index=batch_index + 1,
                    )
                )
                yield table

    if not delivered:
        raise AwsCostAndUsageReportError(
            f"{ERROR_PREFIX}: {NO_MANIFEST} - no billing period under s3://{bucket.strip()}/{base}/metadata/ has a manifest",
            NO_MANIFEST,
        )
    # A retry after a failed finalization would otherwise resume past every batch and load nothing.
    resumable_source_manager.clear_state()


VALIDATION_ERROR_MESSAGES: dict[str, str] = {
    "InvalidAccessKeyId": "AWS rejected the access key. Check the access key ID and secret access key, and that the key is still active.",
    "SignatureDoesNotMatch": "AWS rejected the request signature. Re-enter the secret access key.",
    "ExpiredToken": "The AWS session token has expired. Reconnect with fresh credentials.",
    "TokenRefreshRequired": "The AWS session token has expired. Reconnect with fresh credentials.",
    "InvalidToken": "AWS rejected the session token. Re-enter it, or leave it empty for long-lived keys.",
    "AccessDenied": "These AWS credentials cannot read the export. Grant s3:ListBucket on the bucket and s3:GetObject on the export prefix to the IAM user or role.",
    "NoSuchBucket": "The bucket does not exist. Check the bucket name.",
    # A rejection without an error body reaches the parser as its bare status.
    "HTTP 401": "AWS rejected the access key. Check the access key ID and secret access key, and that the key is still active.",
    "HTTP 403": "These AWS credentials cannot read the export. Grant s3:ListBucket on the bucket and s3:GetObject on the export prefix to the IAM user or role.",
}

WRONG_REGION_MESSAGE = "The bucket is in a different AWS region. Set the region the bucket was created in."

NO_EXPORT_MESSAGE = (
    "No billing periods were found for this export. Check the bucket, S3 path prefix and export name. "
    "AWS can take up to 24 hours to deliver the first export after you create it."
)

GENERIC_VALIDATION_ERROR = "AWS didn't accept the request. Check the access key can read the bucket, then try again."


def validate_credentials(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    aws_region: str,
    bucket: str,
    prefix: Optional[str],
    export_name: str,
    first_billing_period: Optional[str],
) -> tuple[bool, Optional[str]]:
    """Check the inputs, then list the export's partitions once: the call every sync starts with."""
    if not aws_access_key_id or not aws_secret_access_key:
        return False, "AWS access key ID and secret access key are required"
    if not aws_region or aws_dns_suffix(aws_region.strip()) is None:
        return False, "Enter an AWS region code, for example us-east-1."
    if not bucket or not BUCKET_NAME.match(bucket.strip()):
        return False, "Enter the bucket name only, without s3:// or a path."
    if not export_name or not export_name.strip("/ "):
        return False, "Enter the name of the data export."
    try:
        parse_billing_period(first_billing_period)
    except ValueError as error:
        return False, str(error)

    client = S3Client(aws_access_key_id, aws_secret_access_key, aws_session_token, aws_region, bucket)
    try:
        page = client.list_page(f"{export_base(prefix, export_name)}/data/", max_keys=1)
    except AwsCostAndUsageReportError as error:
        code = error.code or ""
        if code in WRONG_REGION_CODES:
            if error.bucket_region:
                return False, f"The bucket is in {error.bucket_region}. Set the AWS region to {error.bucket_region}."
            return False, WRONG_REGION_MESSAGE
        if code in VALIDATION_ERROR_MESSAGES:
            return False, VALIDATION_ERROR_MESSAGES[code]
        capture_exception(error)
        return False, GENERIC_VALIDATION_ERROR
    except requests.RequestException:
        return False, "Could not reach Amazon S3. Check the bucket name and region, then try again."
    except Exception as error:
        capture_exception(error)
        return False, GENERIC_VALIDATION_ERROR

    if not page.prefixes and not page.keys:
        return False, NO_EXPORT_MESSAGE
    return True, None


def aws_cost_and_usage_report_source(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    aws_region: str,
    bucket: str,
    prefix: Optional[str],
    export_name: str,
    first_billing_period: Optional[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CostAndUsageReportResumeConfig],
) -> SourceResponse:
    return SourceResponse(
        name=COST_AND_USAGE,
        items=lambda: get_rows(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            aws_region=aws_region,
            bucket=bucket,
            prefix=prefix,
            export_name=export_name,
            first_billing_period=first_billing_period,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=None,
        partition_keys=[BILLING_PERIOD_COLUMN],
        partition_mode="datetime",
        partition_format="month",
        sort_mode=None,
    )
