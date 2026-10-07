import re
import json
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from posthog.dataclasses import frozen

MAX_BRAND_NAME_LENGTH = 255
_TITLE_SEPARATOR = re.compile(r"\s+[|\-–—·:]\s+")
_WHITESPACE = re.compile(r"\s+")
_HEX_COLOR = re.compile(r"#([0-9a-f]{3}|[0-9a-f]{6})")
_RGB_COLOR = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*[\d.]+%?\s*)?\)")
_RASTER_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
_RASTER_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
_APPLE_TOUCH_ICON_SIZE = 180
_DECLARED_SIZE = re.compile(r"(\d{1,5})x\d{1,5}")
_GENERIC_TITLE_SEGMENTS = frozenset({"home", "homepage", "home page", "welcome", "start"})
_GRAY_CHANNEL_SPREAD = 24
_LIGHT_GRAY_FLOOR = 0xC8
_DARK_GRAY_CEILING = 0x38


@frozen
class LogoCandidate:
    url: str
    size: int


@frozen
class BrandSignals:
    name: str
    theme_color: str | None
    tile_color: str | None
    manifest_url: str | None
    logos: tuple[LogoCandidate, ...]


@frozen
class ManifestSignals:
    theme_color: str | None
    logos: tuple[LogoCandidate, ...]


def read_brand_signals(html: str, page_url: str) -> BrandSignals:
    page = _BrandPageParser(page_url)
    page.feed(html)
    page.close()
    return BrandSignals(
        name=page.brand_name(),
        theme_color=page.theme_color(),
        tile_color=brand_color(page.tile_color),
        manifest_url=page.manifest_url,
        logos=largest_first(page.logos),
    )


def read_manifest_signals(manifest_text: str, manifest_url: str) -> ManifestSignals:
    try:
        manifest = json.loads(manifest_text)
    except ValueError:
        manifest = None
    if not isinstance(manifest, dict):
        return ManifestSignals(theme_color=None, logos=())
    icons = manifest.get("icons")
    return ManifestSignals(
        theme_color=brand_color(manifest.get("theme_color")),
        logos=largest_first(_manifest_logos(icons if isinstance(icons, list) else [], manifest_url)),
    )


@frozen
class ColorChannels:
    red: int
    green: int
    blue: int


def brand_color(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    channels = _color_channels(value.strip().lower())
    if channels is None or _is_neutral(channels):
        return None
    return f"#{channels.red:02x}{channels.green:02x}{channels.blue:02x}"


def largest_first(logos: list[LogoCandidate] | tuple[LogoCandidate, ...]) -> tuple[LogoCandidate, ...]:
    first_by_url: dict[str, LogoCandidate] = {}
    for logo in logos:
        first_by_url.setdefault(logo.url, logo)
    return tuple(sorted(first_by_url.values(), key=lambda logo: -logo.size))


def _color_channels(value: str) -> ColorChannels | None:
    if hex_match := _HEX_COLOR.fullmatch(value):
        digits = hex_match.group(1)
        if len(digits) == 3:
            digits = "".join(digit * 2 for digit in digits)
        return ColorChannels(red=int(digits[0:2], 16), green=int(digits[2:4], 16), blue=int(digits[4:6], 16))
    if rgb_match := _RGB_COLOR.fullmatch(value):
        red, green, blue = (int(channel) for channel in rgb_match.groups())
        if max(red, green, blue) <= 255:
            return ColorChannels(red=red, green=green, blue=blue)
    return None


def _is_neutral(channels: ColorChannels) -> bool:
    values = (channels.red, channels.green, channels.blue)
    lowest, highest = min(values), max(values)
    is_gray = highest - lowest < _GRAY_CHANNEL_SPREAD
    return is_gray and (lowest >= _LIGHT_GRAY_FLOOR or highest <= _DARK_GRAY_CEILING)


def _largest_declared_size(sizes: str | None) -> int:
    declared = _DECLARED_SIZE.findall((sizes or "").lower())
    return max((int(width) for width in declared), default=0)


def _is_raster(url: str, declared_type: str | None) -> bool:
    if declared_type:
        return declared_type.strip().lower() in _RASTER_TYPES
    return urlparse(url).path.lower().endswith(_RASTER_EXTENSIONS)


def _manifest_logos(icons: list[object], manifest_url: str) -> list[LogoCandidate]:
    logos: list[LogoCandidate] = []
    for icon in icons:
        if not isinstance(icon, dict) or not isinstance(icon.get("src"), str):
            continue
        if "monochrome" in str(icon.get("purpose", "")).lower():
            continue
        url = absolute_http_url(manifest_url, icon["src"])
        declared_type = icon.get("type") if isinstance(icon.get("type"), str) else None
        if url and _is_raster(url, declared_type):
            logos.append(LogoCandidate(url=url, size=_largest_declared_size(str(icon.get("sizes", "")))))
    return logos


def absolute_http_url(base_url: str, reference: str) -> str | None:
    try:
        url = urljoin(base_url, reference.strip())
        is_http = urlparse(url).scheme in ("http", "https")
    except ValueError:
        return None
    return url if is_http else None


def _brand_name_from_title(title: str) -> str | None:
    segments = _TITLE_SEPARATOR.split(title)
    return next((segment for segment in segments if segment.lower() not in _GENERIC_TITLE_SEGMENTS), None)


def _clean_text(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()[:MAX_BRAND_NAME_LENGTH]


class _BrandPageParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.site_name = ""
        self.application_name = ""
        self.title = ""
        self.theme_colors: list[tuple[str, str]] = []
        self.tile_color: str | None = None
        self.manifest_url: str | None = None
        self.logos: list[LogoCandidate] = []
        self._inside_title = False
        self._title_read = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): (value or "") for name, value in attrs}
        if tag == "title":
            self._inside_title = not self._title_read
        elif tag == "meta":
            self._read_meta(values)
        elif tag == "link":
            self._read_link(values)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._inside_title:
            self._inside_title = False
            self._title_read = True

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self.title += data

    def brand_name(self) -> str:
        for declared in (self.site_name, self.application_name):
            if name := _clean_text(declared):
                return name
        if title_name := _brand_name_from_title(_clean_text(self.title)):
            return title_name
        return (urlparse(self.page_url).hostname or "").removeprefix("www.")

    def theme_color(self) -> str | None:
        dark_last = sorted(self.theme_colors, key=lambda declared: "dark" in declared[0])
        colors = (brand_color(content) for _media, content in dark_last)
        return next((color for color in colors if color), None)

    def _read_meta(self, values: dict[str, str]) -> None:
        name = values.get("name", "").strip().lower()
        content = values.get("content", "")
        if values.get("property", "").strip().lower() == "og:site_name" and not self.site_name:
            self.site_name = content
        elif name == "application-name" and not self.application_name:
            self.application_name = content
        elif name == "theme-color":
            self.theme_colors.append((values.get("media", "").lower(), content))
        elif name == "msapplication-tilecolor" and self.tile_color is None:
            self.tile_color = content

    def _read_link(self, values: dict[str, str]) -> None:
        rel = set(values.get("rel", "").lower().split())
        href = values.get("href", "")
        if not href.strip():
            return
        url = absolute_http_url(self.page_url, href)
        if url is None:
            return
        if "manifest" in rel and self.manifest_url is None:
            self.manifest_url = url
        elif rel & {"apple-touch-icon", "apple-touch-icon-precomposed"}:
            size = _largest_declared_size(values.get("sizes")) or _APPLE_TOUCH_ICON_SIZE
            self.logos.append(LogoCandidate(url=url, size=size))
        elif "icon" in rel and _is_raster(url, values.get("type")):
            self.logos.append(LogoCandidate(url=url, size=_largest_declared_size(values.get("sizes"))))
