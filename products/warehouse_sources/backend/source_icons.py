from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from django.contrib.staticfiles.finders import BaseFinder
from django.core.checks import CheckMessage
from django.core.files.storage import FileSystemStorage

PLUGIN_SOURCES_DIR = Path(__file__).resolve().parent.parent / "sources"
ICON_URL_PREFIX = "warehouse-sources"
ICON_FILE_NAME = "icon.png"


class SourceIconFinder(BaseFinder):
    """Serve each plugin vendor's `icon.png` from its own directory.

    `products/warehouse_sources/sources/<vendor>/icon.png` is served at
    `/static/warehouse-sources/<vendor>/icon.png`, so a vendor declares that path as its `iconPath`
    and needs no file outside its directory. The frontend build (`frontend/build.mjs`) copies the same
    files to the same path in `frontend/dist`, which the static host and `collectstatic` use. This finder
    covers development, where WhiteNoise asks the finders directly and `dist` can lack the icons. It
    exposes only the icon files, so the vendor code next to them never becomes a static file.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.storage = FileSystemStorage(location=PLUGIN_SOURCES_DIR)
        # collectstatic and WhiteNoise read `prefix` to place the listed files under the URL prefix.
        self.storage.prefix = ICON_URL_PREFIX  # type: ignore[attr-defined]

    @staticmethod
    def _icon_for(path: str) -> Path | None:
        vendor, _, file_name = path.removeprefix(f"{ICON_URL_PREFIX}/").partition("/")
        # A vendor directory is a Python package name, which also rules out `..` and nested paths.
        if not path.startswith(f"{ICON_URL_PREFIX}/") or file_name != ICON_FILE_NAME or not vendor.isidentifier():
            return None
        icon = PLUGIN_SOURCES_DIR / vendor / ICON_FILE_NAME
        return icon if icon.is_file() else None

    def check(self, **kwargs: Any) -> list[CheckMessage]:
        return []

    # A miss returns [] like Django's own finders, not the None that the django-stubs signature
    # declares. `finders.find()` wraps a None result into `[None]`, which is truthy, so WhiteNoise would
    # take it as a hit.
    def find(self, path: str, find_all: bool = False, **kwargs: Any) -> str | list[str]:  # type: ignore[override]
        icon = self._icon_for(path)
        if icon is None:
            return []
        return [str(icon)] if find_all else str(icon)

    def list(self, ignore_patterns: Iterable[str] | None) -> Iterator[tuple[str, FileSystemStorage]]:
        for icon in sorted(PLUGIN_SOURCES_DIR.glob(f"*/{ICON_FILE_NAME}")):
            yield f"{icon.parent.name}/{ICON_FILE_NAME}", self.storage
