import re
import json
import posixpath
from enum import IntEnum

from posthog.dataclasses import frozen
from posthog.models.uploaded_media import MAX_IMAGE_BYTES

from products.workflows.backend.services.brand_detection.files import (
    LOGO_VARIANT,
    MANIFEST,
    THIRD_PARTY_DIRECTORY,
    TreeEntry,
    in_scope,
)

MAX_LOGO_CANDIDATES = 5

PUBLIC_DIRECTORY = re.compile(r"(?:^|/)(?:public|static|assets)/")
OWN_LOGO_NAME = re.compile(r"^(?:logo|logomark|brand)(?:[-_.][^/]*)?\.\w+$", re.IGNORECASE)
TOUCH_ICON_NAME = re.compile(r"^apple-touch-icon(?:[-_.][^/]*)?\.\w+$", re.IGNORECASE)
URL_SUFFIX = re.compile(r"[?#].*$")
FAVICON_NAME = re.compile(r"^favicon(?:[-_.][^/]*)?\.\w+$", re.IGNORECASE)
FORMAT_OF_EXTENSION = {
    "png": "png",
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "gif": "gif",
    "webp": "webp",
    "svg": "svg",
    "ico": "ico",
}


class Source(IntEnum):
    OWN_LOGO = 0
    MANIFEST_ICON = 1
    TOUCH_ICON = 2
    FAVICON = 3


@frozen
class LogoCandidate:
    """An image file of the repository that could be the Email brand logo."""

    path: str
    format: str
    size: int


def rank_logo_candidates(tree: list[TreeEntry], app_root: str, texts: dict[str, str]) -> tuple[LogoCandidate, ...]:
    """Rank the repository's own logo files the media library can take: raster before SVG before ICO, then the
    app's own files, then by where the file was found."""
    sizes = {entry.path: entry.size for entry in tree}
    manifest_icons = _manifest_icon_paths(texts, sizes)
    sources = {
        path: source
        for path in sizes
        if _is_own_image(path, app_root) and (source := _source(path, manifest_icons)) is not None
    }
    ranked = sorted(
        (path for path in sources if 0 < sizes[path] <= MAX_IMAGE_BYTES),
        key=lambda path: (_format_rank(path), not path.startswith(app_root), sources[path], -sizes[path], path),
    )
    return tuple(
        LogoCandidate(path=path, format=_format(path), size=sizes[path]) for path in ranked[:MAX_LOGO_CANDIDATES]
    )


def _is_own_image(path: str, app_root: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (
        _format(path) != ""
        and in_scope(path, app_root)
        and not THIRD_PARTY_DIRECTORY.search(f"/{path}")
        and not LOGO_VARIANT.search(name)
    )


def _source(path: str, manifest_icons: frozenset[str]) -> Source | None:
    name = path.rsplit("/", 1)[-1]
    if not PUBLIC_DIRECTORY.search(path):
        return None
    if OWN_LOGO_NAME.match(name):
        return Source.OWN_LOGO
    if path in manifest_icons:
        return Source.MANIFEST_ICON
    if TOUCH_ICON_NAME.match(name):
        return Source.TOUCH_ICON
    if FAVICON_NAME.match(name):
        return Source.FAVICON
    return None


def _manifest_icon_paths(texts: dict[str, str], tree_paths: dict[str, int]) -> frozenset[str]:
    icons = (
        _resolved_icon_path(path, source)
        for path, text in texts.items()
        if MANIFEST.search(path)
        for source in _icon_sources(text)
    )
    return frozenset(icon for icon in icons if icon in tree_paths)


def _resolved_icon_path(manifest_path: str, source: str) -> str:
    base = _served_root(manifest_path) if source.startswith("/") else posixpath.dirname(manifest_path)
    return posixpath.normpath(posixpath.join(base, URL_SUFFIX.sub("", source).lstrip("/")))


def _served_root(manifest_path: str) -> str:
    """The directory a site serves at ``/``: the public, static or assets directory holding the manifest."""
    match = PUBLIC_DIRECTORY.search(manifest_path)
    return manifest_path[: match.end()] if match else posixpath.dirname(manifest_path)


def _icon_sources(manifest_text: str) -> list[str]:
    try:
        manifest = json.loads(manifest_text)
    except (ValueError, RecursionError):
        return []
    icons = manifest.get("icons") if isinstance(manifest, dict) else None
    if not isinstance(icons, list):
        return []
    return [
        icon["src"]
        for icon in icons
        if isinstance(icon, dict) and isinstance(icon.get("src"), str) and "://" not in icon["src"]
    ]


def _format(path: str) -> str:
    return FORMAT_OF_EXTENSION.get(path.rsplit(".", 1)[-1].lower(), "") if "." in path else ""


def _format_rank(path: str) -> int:
    match _format(path):
        case "svg":
            return 1
        case "ico":
            return 2
    return 0
