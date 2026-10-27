"""Copies the images an imported Customer.io email shows into the team's email media library.

Customer.io serves email images from its own asset hosts, so they stop loading once the team closes its account.
Only those hosts are read, and redirects are not followed.
"""

import re
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
_DOWNLOAD_THREADS = 4


def rehost_images(team: Team, user: User, workflow: dict[str, Any], dry_run: bool) -> RehostedWorkflow:
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

    copied = _copy_images(team, user, all_urls[:_MAX_IMAGES_PER_IMPORT])
    notes: list[ImportNote] = []
    actions = []
    for action in workflow["actions"]:
        html = _html(action)
        if html is None:
            actions.append(action)
            continue
        for url, media_url in copied.items():
            html = html.replace(url, media_url)
        actions.append(_with_html(action, html))
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


def _copy_images(team: Team, user: User, urls: list[str]) -> dict[str, str]:
    """Source URL to media library URL, for every image that is in the library now."""
    copied: dict[str, str] = {}
    to_download: list[str] = []
    for url in urls:
        existing = (
            UploadedMedia.objects.filter(
                team=team, purpose=MEDIA_PURPOSE_EMAIL, file_name=_file_name(url), pending=False
            )
            .order_by("created_at")
            .first()
        )
        if existing is not None:
            copied[url] = existing.get_absolute_url()
        else:
            to_download.append(url)
    with ThreadPoolExecutor(max_workers=_DOWNLOAD_THREADS) as pool:
        downloads = list(pool.map(_download, to_download))
    for url, content in zip(to_download, downloads):
        if content is None:
            continue
        media = _save(team, user, url, content)
        if media is not None:
            copied[url] = media.get_absolute_url()
    return copied


def _download(url: str) -> bytes | None:
    try:
        with requests.get(url, timeout=_TIMEOUT_SECONDS, allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                logger.info("workflows.import.image_download_failed", status=response.status_code)
                return None
            content = b""
            for chunk in response.iter_content(64 * 1024):
                content += chunk
                if len(content) > _MAX_BYTES:
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
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    base = urlsplit(url).path.rsplit("/", 1)[-1] or "image"
    return f"customerio-{digest}-{base}"[:200]


def _html(action: dict[str, Any]) -> str | None:
    if action.get("type") != "function_email":
        return None
    value = (((action.get("config") or {}).get("inputs") or {}).get("email") or {}).get("value") or {}
    html = value.get("html")
    return html if isinstance(html, str) else None


def _with_html(action: dict[str, Any], html: str) -> dict[str, Any]:
    config = action["config"]
    email = config["inputs"]["email"]
    return {
        **action,
        "config": {
            **config,
            "inputs": {**config["inputs"], "email": {**email, "value": {**email["value"], "html": html}}},
        },
    }


def _images(count: int) -> str:
    return "image" if count == 1 else "images"
