import re
from collections.abc import Iterable

from posthog.dataclasses import frozen

from products.workflows.backend.services.brand_detection.colors import (
    contrast_ratio,
    hue_distance,
    is_dark,
    is_near_gray,
    is_near_white,
    is_saturated,
    literal_color,
)
from products.workflows.backend.services.brand_detection.signals import Signal, SignalKind

MAX_CANDIDATES = 5
MIN_ACCENT_HUE_DISTANCE = 30
MIN_TEXT_CONTRAST = 4.5
FALLBACK_TEXT_COLOR = "#111111"
FALLBACK_BACKGROUND_COLOR = "#ffffff"
EMAIL_SAFE_FONT_STACK = "Arial, Helvetica, sans-serif"

NAME_KINDS = (
    SignalKind.MANIFEST_NAME,
    SignalKind.SITE_NAME,
    SignalKind.MANIFEST_SHORT_NAME,
    SignalKind.METADATA_TITLE,
    SignalKind.HTML_TITLE,
    SignalKind.PACKAGE_NAME,
)
PRIMARY_KINDS = (SignalKind.BRAND_TOKEN, SignalKind.PRIMARY_TOKEN, SignalKind.THEME_COLOR, SignalKind.LOGO_FILL)
FONT_KINDS = (
    SignalKind.NEXT_FONT,
    SignalKind.CSS_FONT_SANS,
    SignalKind.TAILWIND_FONT_SANS,
    SignalKind.BODY_FONT_FAMILY,
    SignalKind.GOOGLE_FONTS_LINK,
)

# The light-theme primaries that shadcn/ui ships for each base color, in its v3 (HSL) and v4 (OKLCH) forms.
DEFAULT_THEME_PRIMARIES = frozenset(
    color
    for expression in (
        "222.2 47.4% 11.2%",
        "220.9 39.3% 11%",
        "240 5.9% 10%",
        "0 0% 9%",
        "24 9.8% 10%",
        "oklch(0.208 0.042 265.755)",
        "oklch(0.21 0.034 264.665)",
        "oklch(0.21 0.006 285.885)",
        "oklch(0.205 0 0)",
        "oklch(0.216 0.006 56.043)",
    )
    if (color := literal_color(expression)) is not None
)

NAME_AFFIXES = re.compile(r"^@[\w.-]+/|[-_](?:monorepo|app|root)$")
GENERIC_NAMES = frozenset(
    {"web", "app", "www", "frontend", "client", "dashboard", "root", "monorepo", "main", "site", "platform", "ui"}
)
NOISY_TITLE = re.compile(
    r"^(?:sign in|sign up|log in|login|loading|home|untitled|404|create next app|create react app|react app|vite)\b",
    re.IGNORECASE,
)
TITLE_SEPARATOR = re.compile(r"\s+[|\-–—:·]\s+")


@frozen
class Candidate:
    """One proposed value with the file and line it came from. ``path`` is None for values not read from the repo."""

    value: str
    path: str | None
    line: int | None
    default_theme: bool = False
    font_stack: str | None = None


@frozen
class BrandProposal:
    name: Candidate | None
    primary_color: Candidate | None
    accent_color: Candidate | None
    text_color: Candidate | None
    background_color: Candidate | None
    font_family: Candidate | None


@frozen
class BrandCandidates:
    name: tuple[Candidate, ...]
    primary_color: tuple[Candidate, ...]
    accent_color: tuple[Candidate, ...]
    text_color: tuple[Candidate, ...]
    background_color: tuple[Candidate, ...]
    font_family: tuple[Candidate, ...]


def rank_signals(signals: list[Signal], repository_name: str) -> tuple[BrandProposal, BrandCandidates]:
    names = _name_candidates(signals, repository_name)
    primaries = _primary_candidates(signals)
    accents = _accent_candidates(signals, primaries)
    backgrounds = _background_candidates(signals)
    texts = _text_candidates(signals, backgrounds[0].value)
    fonts = _font_candidates(signals)
    candidates = BrandCandidates(
        name=names,
        primary_color=primaries,
        accent_color=accents,
        text_color=texts,
        background_color=backgrounds,
        font_family=fonts,
    )
    proposal = BrandProposal(
        name=_first(names),
        primary_color=_first(primaries),
        accent_color=_first(accents),
        text_color=_first(texts),
        background_color=_first(backgrounds),
        font_family=_first(fonts),
    )
    return proposal, candidates


def _name_candidates(signals: list[Signal], repository_name: str) -> tuple[Candidate, ...]:
    found = [
        Candidate(value=name, path=signal.path, line=signal.line)
        for signal in _ranked(signals, NAME_KINDS)
        if (name := _clean_name(signal)) is not None
    ]
    repository = Candidate(value=_title_case_slug(repository_name.rsplit("/", 1)[-1]), path=None, line=None)
    return _distinct([*found, repository])


def _clean_name(signal: Signal) -> str | None:
    if signal.kind is SignalKind.PACKAGE_NAME:
        slug = NAME_AFFIXES.sub("", signal.value)
        return None if slug.lower() in GENERIC_NAMES else _title_case_slug(slug)
    if signal.kind in (SignalKind.METADATA_TITLE, SignalKind.HTML_TITLE):
        title = TITLE_SEPARATOR.split(signal.value)[0].strip()
        return None if NOISY_TITLE.match(title) or not title else title
    return None if NOISY_TITLE.match(signal.value) else signal.value


def _title_case_slug(slug: str) -> str:
    return " ".join(word.capitalize() for word in re.split(r"[-_.\s]+", slug) if word)


def _primary_candidates(signals: list[Signal]) -> tuple[Candidate, ...]:
    usable = [signal for signal in _ranked(signals, PRIMARY_KINDS) if not is_near_white(signal.value)]
    first_pass = [signal for signal in usable if not is_near_gray(signal.value)]
    ordered = first_pass + [signal for signal in usable if is_near_gray(signal.value)]
    return _distinct(
        Candidate(
            value=signal.value,
            path=signal.path,
            line=signal.line,
            default_theme=signal.value in DEFAULT_THEME_PRIMARIES,
        )
        for signal in ordered
    )


def _accent_candidates(signals: list[Signal], primaries: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
    primary = _first(primaries)
    tokens = [_color_candidate(signal) for signal in _ranked(signals, (SignalKind.ACCENT_TOKEN,))]
    return _distinct(
        candidate
        for candidate in [*tokens, *primaries[1:]]
        if is_saturated(candidate.value)
        and not is_near_white(candidate.value)
        and (primary is None or _is_distinct_accent(candidate.value, primary.value))
    )


def _is_distinct_accent(color: str, primary: str) -> bool:
    if not is_saturated(primary):
        return color != primary
    return hue_distance(color, primary) >= MIN_ACCENT_HUE_DISTANCE


def _background_candidates(signals: list[Signal]) -> tuple[Candidate, ...]:
    light = [
        _color_candidate(signal)
        for signal in _ranked(signals, (SignalKind.BACKGROUND_TOKEN,))
        if not is_dark(signal.value)
    ]
    return _distinct([*light[:1], Candidate(value=FALLBACK_BACKGROUND_COLOR, path=None, line=None)])


def _text_candidates(signals: list[Signal], background: str) -> tuple[Candidate, ...]:
    readable = [
        _color_candidate(signal)
        for signal in _ranked(signals, (SignalKind.TEXT_TOKEN,))
        if contrast_ratio(signal.value, background) >= MIN_TEXT_CONTRAST
    ]
    return _distinct([*readable[:1], Candidate(value=FALLBACK_TEXT_COLOR, path=None, line=None)])


def _font_candidates(signals: list[Signal]) -> tuple[Candidate, ...]:
    return _distinct(
        Candidate(value=signal.value, path=signal.path, line=signal.line, font_stack=email_font_stack(signal.value))
        for signal in _ranked(signals, FONT_KINDS)
    )


def email_font_stack(family: str) -> str:
    if family.lower() in ("arial", "helvetica"):
        return EMAIL_SAFE_FONT_STACK
    quoted = f"'{family}'" if " " in family else family
    return f"{quoted}, {EMAIL_SAFE_FONT_STACK}"


def _color_candidate(signal: Signal) -> Candidate:
    return Candidate(value=signal.value, path=signal.path, line=signal.line)


def _ranked(signals: list[Signal], kinds: tuple[SignalKind, ...]) -> list[Signal]:
    # A stable sort keeps reading order within a kind, so app files outrank shared packages and ties never move.
    return sorted((signal for signal in signals if signal.kind in kinds), key=lambda signal: kinds.index(signal.kind))


def _distinct(candidates: Iterable[Candidate]) -> tuple[Candidate, ...]:
    seen: set[str] = set()
    distinct = []
    for candidate in candidates:
        if candidate.value.lower() not in seen:
            seen.add(candidate.value.lower())
            distinct.append(candidate)
    return tuple(distinct[:MAX_CANDIDATES])


def _first(candidates: tuple[Candidate, ...]) -> Candidate | None:
    return candidates[0] if candidates else None
