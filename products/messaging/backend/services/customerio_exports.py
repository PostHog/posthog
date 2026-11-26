"""Reads everyone in a Customer.io workspace from a people export, which Customer.io prepares in the background.

The endpoints are at https://docs.customer.io/integrations/api/app/tag/exports/. The customer owns the key, so per
/routing-outbound-api-calls this honors Customer.io's rate limit here rather than going through `posthog/egress/`.
"""

import csv
import time
import base64
import hashlib
import tempfile
import http.client
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from io import TextIOWrapper
from typing import IO, Any
from urllib.parse import urlsplit

from django.conf import settings

import requests

from posthog.dataclasses import frozen
from posthog.security.pinned_requests import SSRFBlockedError, pinned_session

from products.messaging.backend.services.customerio_client import CustomerIOAPIError, CustomerIOClient

POLL_FIRST_DELAY_SECONDS = 2
POLL_MAX_DELAY_SECONDS = 30
MAX_POLL_SECONDS = 20 * 60
DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_TIMEOUT_SECONDS = 30
DOWNLOAD_CHUNK_BYTES = 64 * 1024
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
# Each read of a download has its own timeout, so a server that trickles bytes needs a total limit too.
MAX_DOWNLOAD_SECONDS = 30 * 60
USER_AGENT = "posthog-messaging-import/1.0"
SEGMENT_COLUMN_PREFIX = "_segment:"
UNFOLLOWED_LINK_MESSAGE = "Customer.io sent a download link PostHog won't follow."
INCOMPLETE_MESSAGE = "Customer.io's people export arrived incomplete."
UNREADABLE_MESSAGE = "Customer.io's people export isn't a file PostHog can read."
UNVERIFIABLE_MESSAGE = (
    "Customer.io sent its people export without a size or checksum, so PostHog can't tell it's complete."
)
FIELD_TOO_LARGE_MESSAGE = "A value in Customer.io's people export is larger than PostHog reads."
ROW_TOO_LARGE_MESSAGE = "A person in Customer.io's people export has more data than PostHog reads."
# Customer.io caps a value at 1,000 bytes, so a line this long isn't a person.
MAX_LINE_CHARS = 4 * 1024 * 1024


class ExportError(CustomerIOAPIError):
    """A problem with an export whose message is safe to show."""


class ExportGone(ExportError):
    """This export failed or can't be read. A new one can work."""


class DownloadFailed(ExportError):
    """Downloading the file failed partway. Reading the same export again can work."""


class ExportPending(ExportError):
    """Customer.io is still preparing this export."""


class ExportTooLarge(ExportError):
    """The file is larger than one import reads. A new export is just as large."""


@frozen
class PeopleExport:
    id: int
    total: int


@frozen
class ExportedPerson:
    values: Mapping[str, str]
    # The segments the person is in, of those the export asked about.
    segment_ids: frozenset[str]


@frozen
class OpenExport:
    # The workspace the key belongs to. Customer.io names it only in the path of the download link.
    workspace_id: str
    # The segments the file says who is in.
    segment_ids: frozenset[str]
    people: Iterator[ExportedPerson]


def start_people_export(client: CustomerIOClient, segment_ids: Sequence[str] = ()) -> int:
    """Starts an export of everyone with all their attributes. A segment in the filter adds no one, because the first
    condition matches everyone, and adds a column that says who is in it."""
    everyone = {"attribute": {"field": "cio_id", "operator": "exists"}}
    body = client.post(
        "/exports/customers",
        {"filters": {"or": [everyone, *({"segment": {"id": int(segment_id)}} for segment_id in segment_ids)]}},
    )
    export = body.get("export")
    if not isinstance(export, dict) or not isinstance(export.get("id"), int):
        raise ExportError("Customer.io didn't start the people export.")
    return export["id"]


def wait_for_people_export(client: CustomerIOClient, export_id: int) -> PeopleExport:
    deadline = time.monotonic() + MAX_POLL_SECONDS
    delay: float = POLL_FIRST_DELAY_SECONDS
    while True:
        try:
            export = client.get(f"/exports/{export_id}").get("export")
        except CustomerIOAPIError as e:
            if e.status_code == 404:
                raise ExportGone("Customer.io deleted its people export.") from e
            raise
        if not isinstance(export, dict):
            raise ExportError("Customer.io sent an unexpected response for its people export.")
        match export.get("status"):
            case "done" if isinstance(export.get("total"), int) and not export.get("failed"):
                return PeopleExport(id=export_id, total=export["total"])
            case "pending":
                pass
            case _:
                raise ExportGone("Customer.io couldn't prepare its people export.")
        if time.monotonic() + delay > deadline:
            raise ExportPending("Customer.io hasn't finished its people export yet.")
        time.sleep(delay)
        delay = min(delay * 2, POLL_MAX_DELAY_SECONDS)


@contextmanager
def open_people_export(client: CustomerIOClient, export: PeopleExport) -> Iterator[OpenExport]:
    """The export's people. A file that isn't complete raises, at the latest after its last person."""
    workspaces = client.get("/workspaces").get("workspaces") or []
    url = _download_url(client, export.id)
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        with tempfile.TemporaryFile() as file:
            try:
                _save_file(client, url, file)
            except (ExportGone, DownloadFailed):
                if attempt == DOWNLOAD_ATTEMPTS:
                    raise
                time.sleep(2**attempt)
                # A link works for 15 minutes.
                url = _download_url(client, export.id)
                continue
            yield _read_file(file, export.total, _workspace_id(url, workspaces))
            return


def _download_url(client: CustomerIOClient, export_id: int) -> str:
    try:
        url = client.get(f"/exports/{export_id}/download").get("url")
    except CustomerIOAPIError as e:
        if e.status_code == 404:
            raise ExportGone("Customer.io deleted its people export.") from e
        raise
    if not isinstance(url, str):
        raise ExportGone("Customer.io sent a people export without a download link.")
    return url


def _workspace_id(url: str, workspaces: Sequence[Any]) -> str:
    known = {str(workspace["id"]) for workspace in workspaces if isinstance(workspace, dict) and "id" in workspace}
    named = known.intersection(urlsplit(url).path.split("/")) or known
    # A guess could empty the cohorts of another workspace.
    if len(named) != 1:
        raise ExportError("Customer.io didn't say which workspace the key belongs to.")
    return named.pop()


def _save_file(client: CustomerIOClient, url: str, file: IO[bytes]) -> None:
    # A stand-in for Customer.io in development serves its files from the API's own host.
    local = (settings.DEBUG or settings.TEST) and url.startswith(f"{client.BASE_URL}/")
    try:
        scheme = urlsplit(url).scheme
    except ValueError:
        raise ExportError(UNFOLLOWED_LINK_MESSAGE) from None
    if scheme != "https" and not local:
        raise ExportError(UNFOLLOWED_LINK_MESSAGE)
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    digest = hashlib.md5(usedforsecurity=False)
    size = 0
    # The link itself grants access to everyone's data, so no message or chained exception holds it.
    try:
        with requests.Session() if local else pinned_session(url) as session:
            with session.get(
                url,
                headers={"Accept-Encoding": "identity", "User-Agent": USER_AGENT},
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code >= 500:
                    raise DownloadFailed(f"Customer.io's people export returned HTTP {response.status_code}.")
                if response.status_code != 200:
                    raise ExportGone(f"Customer.io's people export returned HTTP {response.status_code}.")
                if response.headers.get("Content-Encoding", "identity") != "identity":
                    raise ExportGone(UNREADABLE_MESSAGE)
                # The bytes as sent, because requests doesn't notice a body that ends before its stated length, and
                # read1 returns what has arrived, so a server that trickles bytes still meets the deadline.
                while chunk := response.raw._original_response.read1(DOWNLOAD_CHUNK_BYTES):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise ExportTooLarge("Customer.io's people export is larger than one import takes.")
                    if time.monotonic() > deadline:
                        raise DownloadFailed("Customer.io's people export took too long to download.")
                    digest.update(chunk)
                    file.write(chunk)
                stated = response.headers.get("Content-Length", "")
                expected_digest = _stated_md5(response.headers.get("x-goog-hash", ""))
    except SSRFBlockedError:
        raise ExportError(UNFOLLOWED_LINK_MESSAGE) from None
    except (requests.RequestException, http.client.HTTPException, OSError) as e:
        raise DownloadFailed(f"Couldn't download Customer.io's people export ({type(e).__name__}).") from None
    if not stated.isdigit() and not expected_digest:
        # A file cut inside its last value still parses, so only its size or checksum shows it's whole.
        raise ExportError(UNVERIFIABLE_MESSAGE)
    if (stated.isdigit() and size != int(stated)) or (expected_digest and digest.digest() != expected_digest):
        raise DownloadFailed(INCOMPLETE_MESSAGE)
    file.seek(0)


def _stated_md5(header: str) -> bytes | None:
    for part in header.split(","):
        name, _, value = part.strip().partition("=")
        if name == "md5":
            try:
                return base64.b64decode(value, validate=True)
            except ValueError:
                return None
    return None


def _read_file(file: IO[bytes], total: int, workspace_id: str) -> OpenExport:
    reader = csv.reader(_bounded_lines(TextIOWrapper(file, encoding="utf-8-sig", newline="")), strict=True)
    try:
        columns = next(reader, [])
    except (csv.Error, UnicodeDecodeError) as e:
        raise _unreadable(e) from None
    if len(set(columns)) != len(columns) or (total and "cio_id" not in columns):
        raise ExportGone(UNREADABLE_MESSAGE)
    segment_columns = {
        column: segment_id
        for column in columns
        if column.startswith(SEGMENT_COLUMN_PREFIX)
        and (segment_id := column.removeprefix(SEGMENT_COLUMN_PREFIX)).isdigit()
    }
    return OpenExport(
        workspace_id=workspace_id,
        segment_ids=frozenset(segment_columns.values()),
        people=_read_people(reader, columns, segment_columns, total),
    )


def _read_people(
    reader: Iterator[list[str]], columns: list[str], segment_columns: Mapping[str, str], total: int
) -> Iterator[ExportedPerson]:
    read = 0
    try:
        for row in reader:
            if len(row) != len(columns):
                raise ExportGone(INCOMPLETE_MESSAGE)
            read += 1
            values = {column: value for column, value in zip(columns, row) if value}
            yield ExportedPerson(
                values={k: v for k, v in values.items() if not k.startswith(SEGMENT_COLUMN_PREFIX)},
                segment_ids=frozenset(segment_id for column, segment_id in segment_columns.items() if column in values),
            )
    except (csv.Error, UnicodeDecodeError) as e:
        raise _unreadable(e) from None
    if read != total:
        raise ExportGone(f"Customer.io's people export holds {read:,} people, but says it holds {total:,}.")


def _bounded_lines(text: IO[str]) -> Iterator[str]:
    """The file's lines, refusing one that would fill the worker's memory before the csv module checks its width."""
    while line := text.readline(MAX_LINE_CHARS + 1):
        if len(line) > MAX_LINE_CHARS:
            raise ExportTooLarge(ROW_TOO_LARGE_MESSAGE)
        yield line


def _unreadable(error: Exception) -> ExportError:
    # Every new export holds the same value, so a value past the csv module's field limit isn't retried.
    if isinstance(error, csv.Error) and "field limit" in str(error):
        return ExportTooLarge(FIELD_TOO_LARGE_MESSAGE)
    return ExportGone(UNREADABLE_MESSAGE)
