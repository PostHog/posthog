"""Copies images that another email tool hosts into the team's email media library.

Only the tool's own image hosts are read, over https, and redirects are not followed.
"""

import re
import time
import hashlib
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, wait
from http.client import HTTPException
from urllib.parse import urlsplit

import requests
import structlog
from urllib3.exceptions import HTTPError as Urllib3HTTPError

from posthog.models import Team, User
from posthog.models.uploaded_media import MEDIA_PURPOSE_EMAIL, ObjectStorageUnavailable, UploadedMedia, sniff_image

from products.workflows.backend.facade.contracts import EmailImageSource, ImageBudget

logger = structlog.get_logger(__name__)

_AUTHORITY_END = re.compile(r"[/?#]")
# Postgres refuses these in the copy's file name.
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")
_MAX_BYTES = 4 * 1024 * 1024
_TIMEOUT_SECONDS = 10
# The timeout above restarts with every byte, so a host that drips them needs a limit on the whole image.
_MAX_SECONDS_PER_IMAGE = 30
_DOWNLOAD_THREADS = 4


def is_hosted(url: str, source: EmailImageSource) -> bool:
    """Whether `url` is an https address on one of the tool's image hosts, and nothing a parser could read otherwise."""
    try:
        parts = urlsplit(url)
        host, port = (parts.hostname or "").lower(), parts.port
    except ValueError:
        return False
    # Only the path may hold anything else, such as an accented file name, which the request encodes. Read from the
    # URL itself, because `urlsplit` drops tabs and line breaks.
    authority = _AUTHORITY_END.split(url.partition("//")[2], maxsplit=1)[0]
    if not authority.isascii() or not authority.isprintable() or "\\" in authority or _UNSTORABLE.search(url):
        return False
    return (
        parts.scheme == "https"
        and parts.username is None
        and port is None
        and (host in source.hosts or any(host.endswith(f".{suffix}") for suffix in source.host_suffixes))
    )


def copy_images(
    team: Team, user: User, urls: Iterable[str], source: EmailImageSource, budget: ImageBudget
) -> Mapping[str, str]:
    """Source URL to media library URL, for every image that is in the library now."""
    copied: dict[str, str] = {}
    names = {url: file_name(url, source) for url in urls if is_hosted(url, source)}
    existing: dict[str, UploadedMedia] = {}
    # Anyone with media access can upload under these names, so only copies this user saved count as the import's own.
    for media in (
        UploadedMedia.objects.filter(
            team_id=team.pk,
            created_by=user,
            purpose=MEDIA_PURPOSE_EMAIL,
            file_name__in=set(names.values()),
            pending=False,
            archived_at__isnull=True,
        )
        .exclude(media_location__isnull=True)
        .exclude(media_location="")
        .order_by("created_at")
    ):
        existing.setdefault(media.file_name, media)
    # Staff took these down, whoever copied them, so they are neither shown nor copied again.
    taken_down = set(
        UploadedMedia.objects.filter(
            team_id=team.pk,
            purpose=MEDIA_PURPOSE_EMAIL,
            file_name__in=set(names.values()),
            serving_disabled_at__isnull=False,
        ).values_list("file_name", flat=True)
    )
    to_download: list[str] = []
    for url, name in names.items():
        if name in taken_down:
            continue
        if name in existing:
            copied[url] = existing[name].get_absolute_url()
        else:
            to_download.append(url)
    to_download = to_download[: max(budget.remaining, 0)]
    budget.remaining -= len(to_download)
    pool = ThreadPoolExecutor(max_workers=_DOWNLOAD_THREADS)
    try:
        # A few at a time, so at most that many images sit in memory before they are saved.
        for start in range(0, len(to_download), _DOWNLOAD_THREADS):
            if time.monotonic() >= budget.deadline:
                break
            futures = {
                pool.submit(_download, url, budget.deadline): url
                for url in to_download[start : start + _DOWNLOAD_THREADS]
            }
            done, _ = wait(futures, timeout=max(budget.deadline - time.monotonic(), 0))
            for future, url in futures.items():
                content = future.result() if future in done else None
                # Storage can be slow too, so nothing new is saved once the deadline has passed.
                if content is None or time.monotonic() > budget.deadline:
                    continue
                media = _save(team, user, names[url], content)
                if media is not None:
                    copied[url] = media.get_absolute_url()
    finally:
        # A download still running stops at its next read after the deadline, so the caller does not wait for it.
        pool.shutdown(wait=False, cancel_futures=True)
    return copied


def _download(url: str, deadline: float) -> bytes | None:
    deadline = min(deadline, time.monotonic() + _MAX_SECONDS_PER_IMAGE)
    try:
        with requests.get(
            url,
            timeout=_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
            headers={"Accept-Encoding": "identity"},
        ) as response:
            if response.status_code != 200:
                logger.info("workflows.import.image_download_failed", status=response.status_code)
                return None
            # `read1` returns what one socket read gives, so a host that sends a byte at a time can't hold the
            # thread past the deadline. A buffered read waits until it has the whole chunk.
            read = getattr(getattr(response.raw, "_fp", None), "read1", None) or response.raw.read
            content = b""
            while chunk := read(16 * 1024):
                content += chunk
                if len(content) > _MAX_BYTES or time.monotonic() > deadline:
                    logger.info("workflows.import.image_download_failed", reason="too_large_or_slow")
                    return None
            return content
    # The raw read raises socket and HTTP errors itself, outside what requests wraps.
    except (requests.RequestException, OSError, HTTPException, Urllib3HTTPError) as error:
        logger.info("workflows.import.image_download_failed", error=type(error).__name__)
        return None


def _save(team: Team, user: User, name: str, content: bytes) -> UploadedMedia | None:
    sniffed = sniff_image(content)
    if sniffed is None:
        return None
    try:
        media = UploadedMedia.save_content(
            team=team,
            created_by=user,
            file_name=name,
            content_type=sniffed.content_type,
            content=content,
            purpose=MEDIA_PURPOSE_EMAIL,
        )
    except ObjectStorageUnavailable:
        # `save_content` keeps its row before it raises, and that row has no file behind it.
        UploadedMedia.objects.filter(
            team=team, purpose=MEDIA_PURPOSE_EMAIL, file_name=name, media_location__isnull=True
        ).delete()
        return None
    if media is None:
        return None
    media.size_bytes = len(content)
    media.width = sniffed.width
    media.height = sniffed.height
    media.save(update_fields=["size_bytes", "width", "height"])
    return media


def file_name(url: str, source: EmailImageSource) -> str:
    # The digest makes the name unique per source URL, so importing again reuses the copy.
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    base = urlsplit(url).path.rsplit("/", 1)[-1] or "image"
    return f"{source.key}-{digest}-{base}"[:200]
