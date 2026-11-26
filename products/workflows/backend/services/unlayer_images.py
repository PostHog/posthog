"""Copies email images stored on Unlayer's servers into each team's email media library, and points the team's
stored emails at the copies.

The Unlayer files are only read, never changed, so an email that still uses an Unlayer address keeps working.
"""

import re
import html
import time
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote, unquote, urlsplit
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist

import structlog

from posthog.models import Team
from posthog.models.uploaded_media import MEDIA_PURPOSE_EMAIL, ObjectStorageUnavailable, UploadedMedia, sniff_image
from posthog.storage import object_storage

from products.workflows.backend.models.hog_flow.hog_flow import defer_hog_flow_reloads
from products.workflows.backend.models.hog_flow.hog_flow_template import HogFlowTemplate
from products.workflows.backend.services.email_content_rows import (
    TARGETS,
    find_row_ids,
    rewrite_row,
    team_ids_containing,
)
from products.workflows.backend.services.remote_images import FetchedImage, fetch_image

logger = structlog.get_logger(__name__)

UNLAYER_HOST = "assets.unlayer.com"
# The path only, so a query string after it stays where it is. ASCII only, so a lookalike host can't match.
# Inside quotes an address runs to the closing quote, so a file name with a space stays whole.
_UNLAYER_URL = re.compile(
    r"(?<=[\"'])(?:https?:)?//assets\.unlayer\.com/+projects/[0-9]+/[^\"'<>\\?#\n\r\t]+(?=[\"'?#])"
    r"|(?:https?:)?//assets\.unlayer\.com/+projects/[0-9]+/[^\s\"'<>\\?#]+",
    re.IGNORECASE | re.ASCII,
)
# A design stores an image address as its own value, unencoded, so the whole value is the address even with a space.
_WHOLE_VALUE = re.compile(
    r"(?:https?:)?//assets\.unlayer\.com/+projects/[0-9]+/[^\"'<>\\?#{}\n\r\t]+\.(?:png|jpe?g|gif|webp|svg|bmp|ico|avif|tiff?)",
    re.IGNORECASE | re.ASCII,
)
_IMAGE_NAME_THEN_TEXT = re.compile(r"\.(?:png|jpe?g|gif|webp|svg|bmp|ico|avif|tiff?)\s", re.IGNORECASE | re.ASCII)
_PROJECT_PATH = re.compile(r"/projects/([0-9]+)/.+", re.ASCII)
# A URL inside an inline style can be quoted with entities, as in `url(&quot;https://...&quot;)`.
_ENTITY_QUOTE = re.compile(r"&(?:quot|#34|#39|apos);", re.IGNORECASE)
_PER_IMAGE_SECONDS = 30
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_IMAGES_PER_TEAM = 1000

ImageStatus = Literal["copied", "reused", "would_copy", "failed"]
RowStatus = Literal["rewritten", "would_rewrite", "unchanged", "skipped_shared_template", "deleted", "error"]


@dataclass(frozen=False)
class ImageOutcome:
    source: str
    project: str
    status: ImageStatus
    media_id: str | None = None
    media_url: str | None = None
    http_status: int | None = None
    failure: str | None = None
    # Unlayer refuses some sandbox files at their normal address, but serves them at `//projects/...`.
    via_double_slash: bool = False

    @property
    def may_succeed_later(self) -> bool:
        """A failure a later run can fix, unlike a file Unlayer no longer serves or one that is not an image."""
        if self.status != "failed" or self.failure == "taken_down":
            return False
        return (
            self.http_status is None
            or self.http_status == 429
            or self.http_status >= 500
            or self.failure in ("too_slow", "storage_unavailable")
        )


@dataclass(frozen=False)
class RowOutcome:
    target: str
    row_id: str
    status: RowStatus
    rewritten: int = 0
    # Occurrences still pointing at Unlayer after this run, such as an image that could not be copied.
    left_on_unlayer: int = 0
    error: str | None = None


@dataclass(frozen=False)
class TeamReport:
    team_id: int
    images: list[ImageOutcome] = field(default_factory=list)
    rows: list[RowOutcome] = field(default_factory=list)
    # Set when the team was left untouched, such as for having more images than one run copies.
    skipped: str | None = None


class RateLimiter:
    """Spaces requests to Unlayer at least `1 / per_second` apart."""

    def __init__(self, per_second: float, sleep: Callable[[float], None] = time.sleep) -> None:
        self._interval = 1 / per_second if per_second > 0 else 0.0
        self._sleep = sleep
        self._next = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        if now < self._next:
            self._sleep(self._next - now)
        self._next = max(now, self._next) + self._interval


def source_key(url: str) -> str | None:
    """One address per Unlayer file, whatever spelling the email uses, or None if this is not an Unlayer file."""
    source = html.unescape(url)
    if source.startswith("//"):
        source = f"https:{source}"
    parts = urlsplit(source)
    if (
        parts.scheme.lower() not in ("http", "https")
        or parts.hostname != UNLAYER_HOST
        or parts.port is not None
        or parts.username is not None
    ):
        return None
    # `%20` and a literal space name the same file, and so do `/projects` and `//projects`.
    path = quote(unquote("/" + parts.path.lstrip("/")), safe="/")
    # `..`, `.` and empty segments would let one file go by many keys, and so be downloaded and copied many times.
    if not _PROJECT_PATH.fullmatch(path) or any(segment in ("", ".", "..") for segment in path.split("/")[1:]):
        return None
    return f"https://{UNLAYER_HOST}{path}"


def find_source_keys(text: str) -> list[str]:
    """The source key of each Unlayer image address in `text`, once per occurrence."""
    if (key := _whole_value_key(text)) is not None:
        return [key]
    keys = []
    for match in _UNLAYER_URL.finditer(text):
        url = _trimmed(match.group(0))
        key = source_key(url) if url is not None else None
        if key is not None:
            keys.append(key)
    return keys


def _whole_value_key(value: str) -> str | None:
    stripped = value.strip()
    # An image name or a second address after a space means the first address ended there.
    if (
        stripped.lower().count(UNLAYER_HOST) != 1
        or stripped.count("://") > 1
        or not _WHOLE_VALUE.fullmatch(stripped)
        or _IMAGE_NAME_THEN_TEXT.search(stripped)
    ):
        return None
    return source_key(stripped)


def replace_in_blob(blob: Any, copies: dict[str, str]) -> tuple[Any, int]:
    """`blob` with every Unlayer address that has a copy pointing at the copy, and how many were replaced.

    Only string values change, so the rest of the stored JSON stays as it was."""
    count = 0

    def replace_match(match: re.Match[str]) -> str:
        nonlocal count
        found = match.group(0)
        url = _trimmed(found)
        key = source_key(url) if url is not None else None
        if url is None or key is None or key not in copies:
            return found
        count += 1
        return copies[key] + found[len(url) :]

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            if UNLAYER_HOST not in value.lower():
                return value
            if (key := _whole_value_key(value)) is not None and key in copies:
                nonlocal count
                count += 1
                return value.replace(value.strip(), copies[key], 1)
            return _UNLAYER_URL.sub(replace_match, value)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    new_blob = walk(blob)
    return (new_blob, count) if count else (blob, 0)


def count_sources(blob: Any, keys: set[str]) -> int:
    """How many Unlayer addresses in `blob` there are, adding each one's source key to `keys`."""
    total = 0

    def walk(value: Any) -> None:
        nonlocal total
        if isinstance(value, str):
            if UNLAYER_HOST in value.lower():
                for key in find_source_keys(value):
                    keys.add(key)
                    total += 1
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(blob)
    return total


def media_base_url() -> str:
    """Where the copies will be served from, so an operator can check it before a run writes it into emails."""
    return UploadedMedia(id=UUID(int=0)).get_absolute_url().rsplit("/", 1)[0]


def team_ids_with_unlayer_images() -> list[int]:
    return sorted({team_id for target in TARGETS for team_id in team_ids_containing(target, UNLAYER_HOST)})


def copy_team_images(
    team: Team,
    *,
    dry_run: bool,
    fetch: bool,
    limiter: RateLimiter,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_images: int = DEFAULT_MAX_IMAGES_PER_TEAM,
) -> TeamReport:
    """Copy the team's Unlayer images into its media library, then point its stored emails at the copies.

    Safe to run again: copies are found by source address and reused, and rows already pointing at copies have
    nothing left to replace. An image that can't be copied keeps its Unlayer address."""
    report = TeamReport(team_id=team.pk)
    team_ids = [team.pk]

    rows: list[tuple[str, Any]] = []
    keys: set[str] = set()
    for target in TARGETS:
        row_ids = find_row_ids(target, UNLAYER_HOST, team_ids=team_ids)
        if target == "hog_flow_templates":
            shared = _shared_template_ids(team, row_ids)
            for row_id in shared:
                try:
                    left = _count_row(target, row_id, team_ids)
                except ObjectDoesNotExist:
                    report.rows.append(RowOutcome(target=target, row_id=str(row_id), status="deleted"))
                    continue
                report.rows.append(
                    RowOutcome(
                        target=target, row_id=str(row_id), status="skipped_shared_template", left_on_unlayer=left
                    )
                )
            row_ids = [row_id for row_id in row_ids if row_id not in shared]
        for row_id in row_ids:
            try:
                # A dry run of the rewrite reads every content column of the row, which is all this needs.
                rewrite_row(
                    target, row_id, lambda blob: (blob, count_sources(blob, keys)), team_ids=team_ids, dry_run=True
                )
            except ObjectDoesNotExist:
                report.rows.append(RowOutcome(target=target, row_id=str(row_id), status="deleted"))
                continue
            rows.append((target, row_id))

    if len(keys) > max_images:
        report.skipped = f"{len(keys)} images, over the limit of {max_images}"
        return report

    copies: dict[str, str] = {}
    candidates = _existing_copies(team, keys)
    for key in sorted(keys):
        project = _PROJECT_PATH.fullmatch(urlsplit(key).path).group(1)  # type: ignore[union-attr]
        outcome = _copy(
            team,
            key,
            project,
            candidates.get(_file_name(key), []),
            dry_run=dry_run,
            fetch=fetch,
            limiter=limiter,
            max_bytes=max_bytes,
        )
        report.images.append(outcome)
        if outcome.status == "failed":
            logger.info(
                "workflows.unlayer_images.copy_failed",
                team_id=team.pk,
                source=key,
                http_status=outcome.http_status,
                failure=outcome.failure,
                may_succeed_later=outcome.may_succeed_later,
            )
        if outcome.status == "would_copy":
            copies[key] = f"(copy of {key})"
        elif outcome.status in ("copied", "reused") and outcome.media_url is not None:
            copies[key] = outcome.media_url

    # Workers reload the changed workflows once at the end, not once per saved row.
    with defer_hog_flow_reloads():
        for target, row_id in rows:
            report.rows.append(_rewrite(target, row_id, copies, team_ids=team_ids, dry_run=dry_run))
    return report


def _copy(
    team: Team,
    key: str,
    project: str,
    candidates: list[UploadedMedia],
    *,
    dry_run: bool,
    fetch: bool,
    limiter: RateLimiter,
    max_bytes: int,
) -> ImageOutcome:
    # Staff stopped serving an earlier copy, so a new copy would put the image back.
    if any(media.serving_disabled_at is not None for media in candidates):
        return ImageOutcome(key, project, "failed", failure="taken_down")
    if dry_run and not fetch:
        return ImageOutcome(key, project, "would_copy")
    fetched, via_double_slash = _download(key, limiter=limiter, max_bytes=max_bytes)
    outcome = ImageOutcome(
        key, project, "failed", http_status=fetched.status, failure=fetched.failure, via_double_slash=via_double_slash
    )
    if fetched.content is None:
        return outcome
    sniffed = sniff_image(fetched.content)
    if sniffed is None:
        outcome.failure = "not_an_image"
        return outcome
    # Anyone with media access can upload under the copy's name, so a copy is reused only when it holds these bytes.
    digest = hashlib.sha256(fetched.content).digest()
    for media in candidates:
        if media.pending or media.created_by_id is not None or not media.media_location:
            continue
        stored = object_storage.read_bytes(media.media_location, missing_ok=True)
        if stored is not None and hashlib.sha256(stored).digest() == digest:
            outcome.status = "reused"
            outcome.media_id = str(media.pk)
            outcome.media_url = media.get_absolute_url()
            return outcome
    if dry_run:
        outcome.status = "would_copy"
        return outcome
    copy = _save(team, key, fetched.content, sniffed.content_type, sniffed.width, sniffed.height)
    if copy is None:
        outcome.failure = "storage_unavailable"
        return outcome
    outcome.status = "copied"
    outcome.media_id = str(copy.pk)
    outcome.media_url = copy.get_absolute_url()
    return outcome


def _download(key: str, *, limiter: RateLimiter, max_bytes: int) -> tuple[FetchedImage, bool]:
    limiter.wait()
    fetched = fetch_image(key, deadline=time.monotonic() + _PER_IMAGE_SECONDS, max_bytes=max_bytes)
    if fetched.status != 403:
        return fetched, False
    # Same host and file, so this reads nothing the normal address wouldn't. A 403 here is Unlayer's
    # sandbox refusing a file over its bandwidth cap, which it still serves at the doubled slash.
    limiter.wait()
    retry = fetch_image(
        key.replace("/projects/", "//projects/", 1),
        deadline=time.monotonic() + _PER_IMAGE_SECONDS,
        max_bytes=max_bytes,
        keep_double_slash=True,
    )
    # A retry that failed for a reason a later run can fix is reported as that, not as the permanent-looking 403.
    if retry.content is not None:
        return retry, True
    return (fetched, False) if retry.status in (403, 404) else (retry, False)


def _rewrite(target: str, row_id: Any, copies: dict[str, str], *, team_ids: list[int], dry_run: bool) -> RowOutcome:
    outcome = RowOutcome(target=target, row_id=str(row_id), status="unchanged")
    try:
        before = _count_row(target, row_id, team_ids) if dry_run else 0
        outcome.rewritten = rewrite_row(
            target, row_id, lambda blob: replace_in_blob(blob, copies), team_ids=team_ids, dry_run=dry_run
        )
        # Counted from the row as it now stands, so an edit made during the run is reflected.
        outcome.left_on_unlayer = before - outcome.rewritten if dry_run else _count_row(target, row_id, team_ids)
    except ObjectDoesNotExist:
        outcome.status = "deleted"
        return outcome
    except Exception as error:
        logger.exception("workflows.unlayer_images.rewrite_failed", target=target, row_id=str(row_id))
        outcome.status = "error"
        outcome.error = type(error).__name__
        return outcome
    if outcome.rewritten:
        outcome.status = "would_rewrite" if dry_run else "rewritten"
    return outcome


def _count_row(target: str, row_id: Any, team_ids: list[int]) -> int:
    keys: set[str] = set()
    return rewrite_row(target, row_id, lambda blob: (blob, count_sources(blob, keys)), team_ids=team_ids, dry_run=True)


def _shared_template_ids(team: Team, row_ids: list[Any]) -> set[Any]:
    # A template shared with the organization or every team would point other teams' new workflows at this
    # team's copy, which that team could delete, so it stays on Unlayer.
    if not row_ids:
        return set()
    return set(
        HogFlowTemplate.objects.filter(team_id=team.pk, id__in=row_ids)
        .exclude(scope=HogFlowTemplate.Scope.ONLY_TEAM)
        .values_list("id", flat=True)
    )


def _existing_copies(team: Team, keys: set[str]) -> dict[str, list[UploadedMedia]]:
    """Earlier copies by file name, including taken-down ones whose file staff already deleted."""
    names = {_file_name(key) for key in keys}
    copies: dict[str, list[UploadedMedia]] = {}
    if not names:
        return copies
    # `team_id` resolves an environment to its project, which is where `save_content` keeps the copy.
    for media in UploadedMedia.objects.filter(
        team_id=team.pk, purpose=MEDIA_PURPOSE_EMAIL, file_name__in=names
    ).order_by("created_at"):
        copies.setdefault(media.file_name or "", []).append(media)
    return copies


def _save(
    team: Team, key: str, content: bytes, content_type: str, width: int | None, height: int | None
) -> UploadedMedia | None:
    name = _file_name(key)
    try:
        media = UploadedMedia.save_content(
            team=team,
            created_by=None,
            file_name=name,
            content_type=content_type,
            content=content,
            purpose=MEDIA_PURPOSE_EMAIL,
        )
    except ObjectStorageUnavailable:
        # `save_content` keeps its row before it raises, and that row has no file behind it.
        UploadedMedia.objects.filter(
            team_id=team.pk, purpose=MEDIA_PURPOSE_EMAIL, file_name=name, media_location__isnull=True
        ).delete()
        return None
    if media is None or media.pending:
        return None
    media.size_bytes = len(content)
    media.width = width
    media.height = height
    media.save(update_fields=["size_bytes", "width", "height"])
    return media


def _file_name(key: str) -> str:
    # The digest makes the name unique per source file, so a later run finds and reuses the copy.
    digest = hashlib.sha256(key.encode()).hexdigest()[:12]
    base = unquote(urlsplit(key).path.rsplit("/", 1)[-1]) or "image"
    return f"unlayer-{digest}-{base}"[:200]


def _trimmed(found: str) -> str | None:
    """The image address in a match, or None for one built with Liquid, whose real address only exists at send time."""
    entity = _ENTITY_QUOTE.search(found)
    url = found[: entity.start()] if entity else found
    # A parenthesis is part of the address unless it closes a CSS `url(...)` around it.
    end, extra_closing = len(url), url.count(")") - url.count("(")
    while extra_closing > 0 and end > 0 and url[end - 1] == ")":
        end -= 1
        extra_closing -= 1
    url = url[:end].rstrip(",;")
    return None if "{" in url or "%7B" in url.upper() else url
