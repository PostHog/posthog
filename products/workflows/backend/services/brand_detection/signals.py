import re
import json
import bisect
import functools
from enum import StrEnum
from typing import Any

from posthog.dataclasses import frozen

from products.workflows.backend.services.brand_detection.colors import (
    is_saturated,
    literal_color,
    palette_color,
    resolve_color,
)
from products.workflows.backend.services.brand_detection.files import FileKind, file_kind


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
    ACCENT_TOKEN = "accent_token"
    TEXT_TOKEN = "text_token"
    BACKGROUND_TOKEN = "background_token"
    NEXT_FONT = "next_font"
    CSS_FONT_SANS = "css_font_sans"
    TAILWIND_FONT_SANS = "tailwind_font_sans"
    BODY_FONT_FAMILY = "body_font_family"
    GOOGLE_FONTS_LINK = "google_fonts_link"


@frozen
class Signal:
    """One brand value found in a file of the repository."""

    kind: SignalKind
    value: str
    path: str
    line: int


class VariableTable:
    """CSS custom properties of the light theme and SCSS variables, first definition wins."""

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
    line: int


def light_theme_definitions(text: str) -> list[VariableDefinition]:
    light_text = _blank_dark_theme_blocks(text)
    custom_properties = [
        VariableDefinition(name=match.group(1), value=match.group(2).strip(), line=_line_of(light_text, match.start()))
        for match in CUSTOM_PROPERTY.finditer(light_text)
    ]
    scss_variables = [
        VariableDefinition(
            name="$" + match.group(1), value=match.group(2).strip(), line=_line_of(light_text, match.start())
        )
        for match in SCSS_ASSIGNMENT.finditer(light_text)
    ]
    return sorted(custom_properties + scss_variables, key=lambda definition: definition.line)


CUSTOM_PROPERTY = re.compile(r"(?<![\w-])(--[\w-]{1,100})\s*:\s*([^;{}]{1,300});")
SCSS_ASSIGNMENT = re.compile(r"\$([\w-]{1,100})\s*:\s*([^;{}]{1,300});")
DARK_THEME_SELECTOR = re.compile(
    r"(?:\.dark\b|\[data-(?:theme|mode)=['\"]?dark['\"]?\]|@media\s*\(\s*prefers-color-scheme\s*:\s*dark\s*\))"
    r"[^{;]{0,200}\{"
)
BRACE = re.compile(r"[{}]")
NOT_NEWLINE = re.compile(r"[^\n]")
NEWLINE = re.compile(r"\n")
ROLE_PREFIX = re.compile(r"^(?:color|colors|theme|mantine|chakra|bs|ui|tw)[-_]")
SHADCN_SURFACE_VARIABLES = ("--accent", "--secondary")
SHADCN_SURFACE_REFERENCE = re.compile(r"var\(\s*--(?:accent|secondary)\s*\)")

THEME_OBJECT_COLOR = re.compile(
    r"(?<![\w-])['\"]?(brand|primary|accent|secondary)['\"]?\s*:\s*"
    r"(\{[^{}]{0,2000}\}|['\"`][^'\"`]{1,200}['\"`]|colors\.[a-z]+(?:\[\s*['\"]?\d+['\"]?\s*\]|\.\d+)?)"
)
THEME_OBJECT_SHADE = re.compile(r"(?:DEFAULT|main|base|value|500|600)['\"]?\s*:\s*['\"`]([^'\"`]+)['\"`]")
THEME_OBJECT_FIRST_STRING = re.compile(r":\s*['\"`]([^'\"`]+)['\"`]")
PALETTE_REFERENCE = re.compile(r"colors\.([a-z]+)(?:\[\s*['\"]?(\d+)['\"]?\s*\]|\.(\d+))?")

META_TAG = re.compile(r"<meta\b[^>]{0,500}>")
THEME_COLOR_NAME = re.compile(r"name=['\"]theme-color['\"]")
META_CONTENT = re.compile(r"content=['\"]([^'\"]{1,100})['\"]")
NEXT_THEME_COLOR = re.compile(r"themeColor\s*:\s*(?:\[\s*\{[^}]{0,300}?color\s*:\s*)?['\"]([^'\"]{1,100})['\"]")
HTML_TITLE = re.compile(r"<title>([^<{]{2,80})</title>")
SITE_NAME = re.compile(r"(?:siteName|applicationName)\s*:\s*['\"]([^'\"]{2,60})['\"]")
TITLE_DEFAULT = re.compile(r"title\s*:\s*\{\s*default\s*:\s*['\"]([^'\"]{2,80})['\"]")
TITLE_STRING = re.compile(r"(?<![\w.])title\s*:\s*['\"]([^'\"]{2,80})['\"]")

NEXT_FONT_IMPORT = re.compile(r"import\s*\{([^}]{1,500})\}\s*from\s*['\"](?:next/font/google|@next/font/google)['\"]")
CSS_FONT_SANS = re.compile(r"--font-(?:sans|body|base|primary)\s*:\s*([^;{}]{1,300});")
TAILWIND_FONT_SANS = re.compile(r"(?<![\w-])['\"]?(?:sans|body)['\"]?\s*:\s*\[\s*['\"]([^'\"]{1,200})['\"]")
BODY_FONT_FAMILY = re.compile(r"(?:^|[\s,;}])body\s*(?:,[^{]{0,300})?\{[^}]{0,2000}?font-family\s*:\s*([^;}]{1,300})")
GOOGLE_FONTS_LINK = re.compile(r"fonts\.googleapis\.com/css2?\?family=([\w+]{1,100})")
GENERIC_FONT_FAMILIES = frozenset(
    {
        "system-ui",
        "-apple-system",
        "blinkmacsystemfont",
        "ui-sans-serif",
        "ui-serif",
        "ui-monospace",
        "sans-serif",
        "serif",
        "monospace",
        "inherit",
        "initial",
        "segoe ui",
    }
)

SVG_FILL = re.compile(r"(?:fill|stop-color|stroke)\s*[=:]\s*['\"]?(#[0-9a-fA-F]{3,8}|rgb\([^)]{0,100}\))")


def extract_signals(path: str, text: str, variables: VariableTable) -> list[Signal]:
    match file_kind(path):
        case FileKind.PACKAGE:
            return _package_signals(path, text)
        case FileKind.MANIFEST:
            return _manifest_signals(path, text)
        case FileKind.LOGO:
            return _logo_signals(path, text)
        case FileKind.STYLE:
            return _style_signals(path, text, variables)
        case FileKind.TAILWIND_CONFIG | FileKind.THEME_MODULE:
            return _theme_object_signals(path, text, variables) + _font_signals(path, text)
        case FileKind.DOCUMENT:
            return _document_signals(path, text) + _font_signals(path, text)
    return []


def _package_signals(path: str, text: str) -> list[Signal]:
    name = _json_text(_json_object(text), "name")
    if name is None:
        return []
    return [Signal(kind=SignalKind.PACKAGE_NAME, value=name, path=path, line=_line_of_key(text, "name"))]


def _manifest_signals(path: str, text: str) -> list[Signal]:
    manifest = _json_object(text)
    signals = []
    for key, kind in (("name", SignalKind.MANIFEST_NAME), ("short_name", SignalKind.MANIFEST_SHORT_NAME)):
        if (value := _json_text(manifest, key)) is not None:
            signals.append(Signal(kind=kind, value=value, path=path, line=_line_of_key(text, key)))
    theme_color = manifest.get("theme_color")
    if isinstance(theme_color, str) and (color := literal_color(theme_color.strip())):
        signals.append(
            Signal(kind=SignalKind.THEME_COLOR, value=color, path=path, line=_line_of_key(text, "theme_color"))
        )
    return signals


def _logo_signals(path: str, text: str) -> list[Signal]:
    first_line: dict[str, int] = {}
    counts: dict[str, int] = {}
    for match in SVG_FILL.finditer(text):
        color = literal_color(match.group(1))
        if color is None or not is_saturated(color):
            continue
        counts[color] = counts.get(color, 0) + 1
        first_line.setdefault(color, _line_of(text, match.start()))
    if not counts:
        return []
    dominant = min(counts, key=lambda color: (-counts[color], color))
    return [Signal(kind=SignalKind.LOGO_FILL, value=dominant, path=path, line=first_line[dominant])]


def _style_signals(path: str, text: str, variables: VariableTable) -> list[Signal]:
    signals = [
        Signal(kind=kind, value=color, path=path, line=definition.line)
        for definition in light_theme_definitions(text)
        if (kind := _variable_kind(definition.name, definition.value)) is not None
        and (color := variables.resolve(definition.value)) is not None
    ]
    return signals + _font_signals(path, text)


def _variable_kind(name: str, raw_value: str) -> SignalKind | None:
    if name in SHADCN_SURFACE_VARIABLES:
        return None
    role = ROLE_PREFIX.sub("", name.lstrip("-$").lower())
    return _role_kind(role, raw_value)


def _role_kind(role: str, raw_value: str) -> SignalKind | None:
    for prefix, kind in (
        ("brand", SignalKind.BRAND_TOKEN),
        ("primary", SignalKind.PRIMARY_TOKEN),
        ("accent", SignalKind.ACCENT_TOKEN),
        ("secondary", SignalKind.ACCENT_TOKEN),
    ):
        if re.fullmatch(rf"{prefix}(?:[-_](?:default|main|base|color|500|600))?|{prefix}[-_]color", role):
            if kind is SignalKind.ACCENT_TOKEN and SHADCN_SURFACE_REFERENCE.search(raw_value):
                return None
            return kind
    if role in ("theme-color", "theme_color"):
        return SignalKind.THEME_COLOR
    if role in ("background", "bg", "body-bg"):
        return SignalKind.BACKGROUND_TOKEN
    if role in ("foreground", "fg", "text", "text-color", "body-color"):
        return SignalKind.TEXT_TOKEN
    return None


def _theme_object_signals(path: str, text: str, variables: VariableTable) -> list[Signal]:
    signals = []
    for match in THEME_OBJECT_COLOR.finditer(text):
        raw = _theme_object_value(match.group(2))
        kind = _role_kind(match.group(1), raw)
        color = _palette_reference_color(raw) or variables.resolve(raw)
        if kind is not None and color is not None:
            signals.append(Signal(kind=kind, value=color, path=path, line=_line_of(text, match.start())))
    return signals


def _theme_object_value(body: str) -> str:
    if not body.startswith("{"):
        return body
    shade = THEME_OBJECT_SHADE.search(body) or THEME_OBJECT_FIRST_STRING.search(body)
    return shade.group(1) if shade else ""


def _palette_reference_color(raw: str) -> str | None:
    match = PALETTE_REFERENCE.fullmatch(raw)
    if match is None:
        return None
    return palette_color(match.group(1), match.group(2) or match.group(3) or "500")


def _document_signals(path: str, text: str) -> list[Signal]:
    signals = []
    for tag in META_TAG.finditer(text):
        if THEME_COLOR_NAME.search(tag.group()) and (color := _meta_content_color(tag.group())):
            signals.append(
                Signal(kind=SignalKind.THEME_COLOR, value=color, path=path, line=_line_of(text, tag.start()))
            )
    for match in NEXT_THEME_COLOR.finditer(text):
        if color := literal_color(match.group(1)):
            signals.append(
                Signal(kind=SignalKind.THEME_COLOR, value=color, path=path, line=_line_of(text, match.start()))
            )
    for pattern, kind in (
        (SITE_NAME, SignalKind.SITE_NAME),
        (TITLE_DEFAULT, SignalKind.METADATA_TITLE),
        (TITLE_STRING, SignalKind.METADATA_TITLE),
        (HTML_TITLE, SignalKind.HTML_TITLE),
    ):
        for match in pattern.finditer(text):
            signals.append(
                Signal(kind=kind, value=match.group(1).strip(), path=path, line=_line_of(text, match.start()))
            )
    return signals


def _meta_content_color(tag: str) -> str | None:
    content = META_CONTENT.search(tag)
    return literal_color(content.group(1)) if content else None


def _font_signals(path: str, text: str) -> list[Signal]:
    signals = []
    for match in NEXT_FONT_IMPORT.finditer(text):
        families = [_next_font_family(name) for name in match.group(1).split(",") if name.strip()]
        for imported in sorted(families, key=lambda family: family.endswith(" Mono")):
            signals.append(
                Signal(kind=SignalKind.NEXT_FONT, value=imported, path=path, line=_line_of(text, match.start()))
            )
    for pattern, kind in (
        (CSS_FONT_SANS, SignalKind.CSS_FONT_SANS),
        (TAILWIND_FONT_SANS, SignalKind.TAILWIND_FONT_SANS),
        (BODY_FONT_FAMILY, SignalKind.BODY_FONT_FAMILY),
    ):
        for match in pattern.finditer(text):
            if named := first_named_font_family(match.group(1)):
                signals.append(Signal(kind=kind, value=named, path=path, line=_line_of(text, match.start(1))))
    for match in GOOGLE_FONTS_LINK.finditer(text):
        signals.append(
            Signal(
                kind=SignalKind.GOOGLE_FONTS_LINK,
                value=match.group(1).replace("+", " "),
                path=path,
                line=_line_of(text, match.start()),
            )
        )
    return signals


def _next_font_family(imported_name: str) -> str:
    return imported_name.strip().split(" as ")[0].strip().replace("_", " ")


def first_named_font_family(stack: str) -> str | None:
    for family in stack.split(","):
        name = family.strip().strip("'\"` ")
        if name and not name.startswith(("var(", "$", "theme(")) and name.lower() not in GENERIC_FONT_FAMILIES:
            return name
    return None


def _json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_text(parsed: dict[str, Any], key: str) -> str | None:
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


def _line_of_key(text: str, key: str) -> int:
    match = re.search(rf'"{re.escape(key)}"\s*:', text)
    return _line_of(text, match.start()) if match else 1


def _line_of(text: str, offset: int) -> int:
    return bisect.bisect_left(_newline_offsets(text), offset) + 1


# A file is located once per signal, so the offsets are computed once per file instead of once per lookup.
@functools.lru_cache(maxsize=4)
def _newline_offsets(text: str) -> tuple[int, ...]:
    return tuple(match.start() for match in NEWLINE.finditer(text))


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
