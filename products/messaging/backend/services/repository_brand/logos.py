import re
import json
import posixpath
from enum import IntEnum

from products.messaging.backend.services.repository_brand.files import (
    LOGO_VARIANT,
    MANIFEST,
    THIRD_PARTY_DIRECTORY,
    TreeEntry,
    in_scope,
)

MAX_LOGO_CANDIDATES = 3
MAX_LOGO_BYTES = 4 * 1024 * 1024 - 1

PUBLIC_DIRECTORY = re.compile(r"(?:^|/)(?:public|static|assets)/")
RASTER_IMAGE = re.compile(r"\.(?:png|jpe?g|gif|webp)$", re.IGNORECASE)
OWN_LOGO_NAME = re.compile(r"^(?:logo|logomark|brand)(?:[-_.][^/]*)?\.\w+$", re.IGNORECASE)
TOUCH_ICON_NAME = re.compile(r"^apple-touch-icon(?:[-_.][^/]*)?\.\w+$", re.IGNORECASE)
FAVICON_NAME = re.compile(r"^favicon(?:[-_.][^/]*)?\.\w+$", re.IGNORECASE)
URL_SUFFIX = re.compile(r"[?#].*$")


class LogoSource(IntEnum):
    OWN_LOGO = 0
    MANIFEST_ICON = 1
    TOUCH_ICON = 2
    FAVICON = 3


def rank_logo_paths(tree: list[TreeEntry], app_root: str, texts: dict[str, str]) -> tuple[str, ...]:
    sizes = {entry.path: entry.size for entry in tree}
    manifest_icons = _manifest_icon_paths(texts, sizes)
    sources = {
        path: source
        for path, size in sizes.items()
        if 0 < size <= MAX_LOGO_BYTES
        and _is_own_raster_image(path, app_root)
        and (source := _logo_source(path, manifest_icons)) is not None
    }
    ranked = sorted(
        sources, key=lambda path: (not path.startswith(app_root), sources[path], path.count("/"), -sizes[path], path)
    )
    return tuple(ranked[:MAX_LOGO_CANDIDATES])


def _is_own_raster_image(path: str, app_root: str) -> bool:
    return (
        bool(RASTER_IMAGE.search(path))
        and in_scope(path, app_root)
        and not THIRD_PARTY_DIRECTORY.search(f"/{path}")
        and not LOGO_VARIANT.search(posixpath.basename(path))
    )


def _logo_source(path: str, manifest_icons: frozenset[str]) -> LogoSource | None:
    name = posixpath.basename(path)
    if not PUBLIC_DIRECTORY.search(path):
        return None
    if OWN_LOGO_NAME.match(name):
        return LogoSource.OWN_LOGO
    if path in manifest_icons:
        return LogoSource.MANIFEST_ICON
    if TOUCH_ICON_NAME.match(name):
        return LogoSource.TOUCH_ICON
    if FAVICON_NAME.match(name):
        return LogoSource.FAVICON
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
