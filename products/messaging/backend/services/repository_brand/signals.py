import re
import json
from enum import StrEnum

from posthog.dataclasses import frozen

from products.messaging.backend.services.repository_brand.colors import (
    is_saturated,
    literal_color,
    palette_color,
    resolve_color,
)
from products.messaging.backend.services.repository_brand.files import FileKind, file_kind


class SignalKind(StrEnum):
    MANIFEST_NAME = "manifest_name"
    SITE_NAME = "site_name"
    MANIFEST_SHORT_NAME = "manifest_short_name"
    METADATA_TITLE = "metadata_title"
    HTML_TITLE = "html_title"
    PACKAGE_NAME = "package_name"
    BRAND_TOKEN = "brand_token"
    PRIMARY_TOKEN = "primary_token"
    THEME_COLOR = "theme_color"
    LOGO_FILL = "logo_fill"


@frozen
class Signal:
    kind: SignalKind
    value: str


class VariableTable:
    def __init__(self) -> None:
        self._variables: dict[str, str] = {}

    @classmethod
    def from_style_files(cls, texts: dict[str, str]) -> "VariableTable":
        table = cls()
        for path, text in texts.items():
            if file_kind(path) is FileKind.STYLE:
                table._collect(text)
        return table

    def raw(self, name: str) -> str | None:
        return self._variables.get(name)

    def resolve(self, raw: str) -> str | None:
        return resolve_color(raw, self.raw)

    def _collect(self, text: str) -> None:
        for definition in light_theme_definitions(text):
            self._variables.setdefault(definition.name, definition.value)


@frozen
class VariableDefinition:
    name: str
    value: str
    offset: int


def light_theme_definitions(text: str) -> list[VariableDefinition]:
    light_text = _blank_dark_theme_blocks(text)
    custom_properties = [
        VariableDefinition(name=match.group(1), value=match.group(2).strip(), offset=match.start())
        for match in CUSTOM_PROPERTY.finditer(light_text)
    ]
    scss_variables = [
        VariableDefinition(name="$" + match.group(1), value=match.group(2).strip(), offset=match.start())
        for match in SCSS_ASSIGNMENT.finditer(light_text)
    ]
    return sorted(custom_properties + scss_variables, key=lambda definition: definition.offset)


CUSTOM_PROPERTY = re.compile(r"(?<![\w-])(--[\w-]{1,100})\s*:\s*([^;{}\s][^;{}]{0,299})(?=[;}])")
SCSS_ASSIGNMENT = re.compile(r"\$([\w-]{1,100})\s*:\s*([^;{}\s][^;{}]{0,299})(?=[;}])")
DARK_THEME_SELECTOR = re.compile(
    r"(?:\.dark\b|\[data-(?:theme|mode)=['\"]?dark['\"]?\]|@media\s*\(\s*prefers-color-scheme\s*:\s*dark\s*\))"
    r"[^{;]{0,200}\{"
)
BRACE = re.compile(r"[{}]")
NOT_NEWLINE = re.compile(r"[^\n]")
ROLE_PREFIX = re.compile(r"^(?:color|colors|theme|mantine|chakra|bs|ui|tw)[-_]")
THEME_OBJECT_COLOR = re.compile(
    r"(?<![\w-])['\"]?(brand|primary)['\"]?\s*:\s*"
    r"(\{[^{}]{0,2000}\}|['\"`][^'\"`]{1,200}['\"`]|colors\.[a-z]+(?:\[\s*['\"]?\d+['\"]?\s*\]|\.\d+)?)"
)
THEME_OBJECT_SHADES = tuple(
    re.compile(rf"(?<![\w-])['\"]?{key}['\"]?\s*:\s*['\"`]([^'\"`]+)['\"`]")
    for key in ("DEFAULT", "main", "base", "value", "500", "600")
)
THEME_OBJECT_FIRST_STRING = re.compile(r":\s*['\"`]([^'\"`]+)['\"`]")
PALETTE_REFERENCE = re.compile(r"colors\.([a-z]+)(?:\[\s*['\"]?(\d+)['\"]?\s*\]|\.(\d+))?")

META_TAG = re.compile(r"<meta\b[^>]{0,500}>")
THEME_COLOR_NAME = re.compile(r"name=['\"]theme-color['\"]")
META_CONTENT = re.compile(r"content=['\"]([^'\"]{1,100})['\"]")
NEXT_THEME_COLOR = re.compile(r"themeColor\s*:\s*(?:\[\s*\{[^}]{0,300}?color\s*:\s*)?['\"]([^'\"]{1,100})['\"]")
HTML_TITLE = re.compile(r"<title>([^<{]{2,80})</title>")
SITE_NAME = re.compile(r"(?:siteName|applicationName)\s*:\s*['\"]([^'\"]{2,60})['\"]")
TITLE_DEFAULT = re.compile(r"title\s*:\s*\{[^{}]{0,300}?(?<![\w])default\s*:\s*['\"]([^'\"]{2,80})['\"]")
TITLE_STRING = re.compile(r"(?<![\w.])title\s*:\s*['\"]([^'\"]{2,80})['\"]")

SVG_FILL = re.compile(r"(?:fill|stop-color|stroke)\s*[=:]\s*['\"]?(#[0-9a-fA-F]{3,8}|rgb\([^)]{0,100}\))")


def extract_signals(path: str, text: str, variables: VariableTable) -> list[Signal]:
    match file_kind(path):
        case FileKind.PACKAGE:
            return _package_signals(text)
        case FileKind.MANIFEST:
            return _manifest_signals(text)
        case FileKind.LOGO:
            return _logo_signals(text)
        case FileKind.STYLE:
            return _style_signals(text, variables)
        case FileKind.TAILWIND_CONFIG | FileKind.THEME_MODULE:
            return _theme_object_signals(text, variables)
        case FileKind.DOCUMENT:
            return _document_signals(text)
    return []


def _package_signals(text: str) -> list[Signal]:
    name = _json_text(_json_object(text), "name")
    if name is None:
        return []
    return [Signal(kind=SignalKind.PACKAGE_NAME, value=name)]


def _manifest_signals(text: str) -> list[Signal]:
    manifest = _json_object(text)
    signals = []
    for key, kind in (("name", SignalKind.MANIFEST_NAME), ("short_name", SignalKind.MANIFEST_SHORT_NAME)):
        if (value := _json_text(manifest, key)) is not None:
            signals.append(Signal(kind=kind, value=value))
    theme_color = manifest.get("theme_color")
    if isinstance(theme_color, str) and (color := literal_color(theme_color.strip())):
        signals.append(Signal(kind=SignalKind.THEME_COLOR, value=color))
    return signals


def _logo_signals(text: str) -> list[Signal]:
    counts: dict[str, int] = {}
    for match in SVG_FILL.finditer(text):
        color = literal_color(match.group(1))
        if color is None or not is_saturated(color):
            continue
        counts[color] = counts.get(color, 0) + 1
    if not counts:
        return []
    dominant = min(counts, key=lambda color: (-counts[color], color))
    return [Signal(kind=SignalKind.LOGO_FILL, value=dominant)]


def _style_signals(text: str, variables: VariableTable) -> list[Signal]:
    return [
        Signal(kind=kind, value=color)
        for definition in light_theme_definitions(text)
        if (kind := _variable_kind(definition.name)) is not None
        and (color := variables.resolve(definition.value)) is not None
    ]


def _variable_kind(name: str) -> SignalKind | None:
    return _role_kind(ROLE_PREFIX.sub("", name.lstrip("-$").lower()))


def _role_kind(role: str) -> SignalKind | None:
    for prefix, kind in (
        ("brand", SignalKind.BRAND_TOKEN),
        ("primary", SignalKind.PRIMARY_TOKEN),
    ):
        if re.fullmatch(rf"{prefix}(?:[-_](?:default|main|base|color|500|600))?", role):
            return kind
    if role in ("theme-color", "theme_color"):
        return SignalKind.THEME_COLOR
    return None


def _theme_object_signals(text: str, variables: VariableTable) -> list[Signal]:
    signals = []
    for match in THEME_OBJECT_COLOR.finditer(text):
        raw = _theme_object_value(match.group(2))
        kind = _role_kind(match.group(1))
        color = _palette_reference_color(raw) or variables.resolve(raw)
        if kind is not None and color is not None:
            signals.append(Signal(kind=kind, value=color))
    return signals


def _theme_object_value(body: str) -> str:
    if not body.startswith("{"):
        return body
    shade = next(
        (match for pattern in THEME_OBJECT_SHADES if (match := pattern.search(body))),
        THEME_OBJECT_FIRST_STRING.search(body),
    )
    return shade.group(1) if shade else ""


def _palette_reference_color(raw: str) -> str | None:
    match = PALETTE_REFERENCE.fullmatch(raw)
    if match is None:
        return None
    return palette_color(match.group(1), match.group(2) or match.group(3) or "500")


def _document_signals(text: str) -> list[Signal]:
    signals = []
    for tag in META_TAG.finditer(text):
        if THEME_COLOR_NAME.search(tag.group()) and (color := _meta_content_color(tag.group())):
            signals.append(Signal(kind=SignalKind.THEME_COLOR, value=color))
    for match in NEXT_THEME_COLOR.finditer(text):
        if color := literal_color(match.group(1)):
            signals.append(Signal(kind=SignalKind.THEME_COLOR, value=color))
    for pattern, kind in (
        (SITE_NAME, SignalKind.SITE_NAME),
        (TITLE_DEFAULT, SignalKind.METADATA_TITLE),
        (TITLE_STRING, SignalKind.METADATA_TITLE),
        (HTML_TITLE, SignalKind.HTML_TITLE),
    ):
        for match in pattern.finditer(text):
            signals.append(Signal(kind=kind, value=match.group(1).strip()))
    return signals


def _meta_content_color(tag: str) -> str | None:
    content = META_CONTENT.search(tag)
    return literal_color(content.group(1)) if content else None


def _json_object(text: str) -> dict[str, object]:
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_text(parsed: dict[str, object], key: str) -> str | None:
    value = parsed.get(key)
    if not isinstance(value, str) or not value.strip() or not _is_valid_unicode(value):
        return None
    return value.strip()


def _is_valid_unicode(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _blank_dark_theme_blocks(text: str) -> str:
    pieces = []
    position = 0
    while selector := DARK_THEME_SELECTOR.search(text, position):
        block_end = _end_of_block(text, selector.end())
        pieces += [text[position : selector.start()], NOT_NEWLINE.sub(" ", text[selector.start() : block_end])]
        position = block_end
    return "".join([*pieces, text[position:]])


def _end_of_block(text: str, after_opening_brace: int) -> int:
    depth = 1
    for brace in BRACE.finditer(text, after_opening_brace):
        depth += 1 if brace.group() == "{" else -1
        if depth == 0:
            return brace.end()
    return len(text)
