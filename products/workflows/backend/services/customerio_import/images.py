"""Copies the images an imported Customer.io email shows into the team's email media library.

Customer.io serves email images from its own asset hosts, so they stop loading once the team closes its account.
Only those hosts are read, and redirects are not followed.
"""

import re
import html
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlsplit

import requests
import structlog

from posthog.models import Team, User
from posthog.models.uploaded_media import MEDIA_PURPOSE_EMAIL, ObjectStorageUnavailable, UploadedMedia, sniff_image

from products.workflows.backend.facade.contracts import ImportNote, RehostedWorkflow
from products.workflows.backend.facade.enums import WorkflowImportNoteLevel

logger = structlog.get_logger(__name__)

_ASSET_URL = re.compile(r"https://[a-z0-9-]+\.customeriomail\.com/[^\s\"'()<>]+", re.IGNORECASE)
_MAX_BYTES = 4 * 1024 * 1024
_MAX_IMAGES_PER_IMPORT = 100
_TIMEOUT_SECONDS = 10
_DOWNLOAD_DEADLINE_SECONDS = 30
_DOWNLOAD_THREADS = 4


class ImageBudget:
    """How many more images one import request may download, shared by every automation in it."""

    def __init__(self, remaining: int = _MAX_IMAGES_PER_IMPORT) -> None:
        self.remaining = remaining

    def take(self, urls: list[str]) -> list[str]:
        taken = urls[: self.remaining]
        self.remaining -= len(taken)
        return taken


def rehost_images(
    team: Team, user: User, workflow: dict[str, Any], dry_run: bool, budget: ImageBudget
) -> RehostedWorkflow:
    """The workflow with every Customer.io-hosted email image pointing at a copy in the media library."""
    steps = [action for action in workflow["actions"] if _html(action) is not None]
    urls_by_step = {action["id"]: list(dict.fromkeys(_ASSET_URL.findall(_html(action) or ""))) for action in steps}
    all_urls = list(dict.fromkeys(url for urls in urls_by_step.values() for url in urls))
    if not all_urls:
        return RehostedWorkflow(workflow=workflow, notes=())
    if dry_run:
        return RehostedWorkflow(
            workflow=workflow,
            notes=(
                ImportNote(
                    level=WorkflowImportNoteLevel.APPROXIMATED,
                    message=f"{len(all_urls)} email {_images(len(all_urls))} on Customer.io's servers will be "
                    "copied into your email media library when you import.",
                ),
            ),
        )

    copied = _copy_images(team, user, all_urls, budget)
    notes: list[ImportNote] = []
    actions = []
    for action in workflow["actions"]:
        body = _html(action)
        if body is None:
            actions.append(action)
            continue
        # One pass over whole matches, so a URL that starts with another copied URL keeps its own copy.
        body = _ASSET_URL.sub(lambda match: copied.get(match.group(0), match.group(0)), body)
        actions.append(_with_html(action, body))
        missed = [url for url in urls_by_step.get(action["id"], []) if url not in copied]
        if missed:
            notes.append(
                ImportNote(
                    level=WorkflowImportNoteLevel.NEEDS_INPUT,
                    message=f"{len(missed)} {_images(len(missed))} could not be copied from Customer.io and still "
                    f"load from its servers: {', '.join(missed[:3])}{'…' if len(missed) > 3 else ''}. Upload "
                    "them to the media library before you close your Customer.io account.",
                    step_id=action["id"],
                    step_name=action.get("name"),
                )
            )
    return RehostedWorkflow(workflow={**workflow, "actions": actions}, notes=tuple(notes))


def _copy_images(team: Team, user: User, urls: list[str], budget: ImageBudget) -> dict[str, str]:
    """Source URL, as the HTML writes it, to media library URL, for every image that is in the library now."""
    copied: dict[str, str] = {}
    to_download: list[str] = []
    for url in urls:
        existing = (
            UploadedMedia.objects.filter(
                team=team, purpose=MEDIA_PURPOSE_EMAIL, file_name=_file_name(url), pending=False
            )
            .exclude(media_location__isnull=True)
            .exclude(media_location="")
            .order_by("created_at")
            .first()
        )
        if existing is not None:
            copied[url] = existing.get_absolute_url()
        else:
            to_download.append(url)
    to_download = budget.take(to_download)
    with ThreadPoolExecutor(max_workers=_DOWNLOAD_THREADS) as pool:
        # A few at a time, so at most that many images sit in memory before they are saved.
        for start in range(0, len(to_download), _DOWNLOAD_THREADS):
            batch = to_download[start : start + _DOWNLOAD_THREADS]
            for url, content in zip(batch, pool.map(_download, batch)):
                media = _save(team, user, url, content) if content is not None else None
                if media is not None:
                    copied[url] = media.get_absolute_url()
    return copied


def _download(url: str) -> bytes | None:
    # Browsers read `&amp;` in an attribute as `&`, so the request has to as well.
    source = html.unescape(url)
    deadline = time.monotonic() + _DOWNLOAD_DEADLINE_SECONDS
    try:
        with requests.get(source, timeout=_TIMEOUT_SECONDS, allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                logger.info("workflows.import.image_download_failed", status=response.status_code)
                return None
            content = b""
            for chunk in response.iter_content(64 * 1024):
                content += chunk
                if len(content) > _MAX_BYTES or time.monotonic() > deadline:
                    logger.info("workflows.import.image_download_failed", reason="too_large_or_slow")
                    return None
            return content
    except requests.RequestException as error:
        logger.info("workflows.import.image_download_failed", error=type(error).__name__)
        return None


def _save(team: Team, user: User, url: str, content: bytes) -> UploadedMedia | None:
    sniffed = sniff_image(content)
    if sniffed is None:
        return None
    try:
        media = UploadedMedia.save_content(
            team=team,
            created_by=user,
            file_name=_file_name(url),
            content_type=sniffed.content_type,
            content=content,
            purpose=MEDIA_PURPOSE_EMAIL,
        )
    except ObjectStorageUnavailable:
        # `save_content` keeps its row before it raises, and that row has no file behind it.
        UploadedMedia.objects.filter(
            team=team, purpose=MEDIA_PURPOSE_EMAIL, file_name=_file_name(url), media_location__isnull=True
        ).delete()
        return None
    if media is None:
        return None
    media.size_bytes = len(content)
    media.width = sniffed.width
    media.height = sniffed.height
    media.save(update_fields=["size_bytes", "width", "height"])
    return media


def _file_name(url: str) -> str:
    # The digest makes the name unique per source URL, so importing again reuses the copy.
    source = html.unescape(url)
    digest = hashlib.sha256(source.encode()).hexdigest()[:12]
    base = urlsplit(source).path.rsplit("/", 1)[-1] or "image"
    return f"customerio-{digest}-{base}"[:200]


def _html(action: dict[str, Any]) -> str | None:
    if action.get("type") != "function_email":
        return None
    value = (((action.get("config") or {}).get("inputs") or {}).get("email") or {}).get("value") or {}
    html = value.get("html")
    return html if isinstance(html, str) else None


def _with_html(action: dict[str, Any], body: str) -> dict[str, Any]:
    config = action["config"]
    email = config["inputs"]["email"]
    return {
        **action,
        "config": {
            **config,
            "inputs": {**config["inputs"], "email": {**email, "value": {**email["value"], "html": body}}},
        },
    }


def _images(count: int) -> str:
    return "image" if count == 1 else "images"
