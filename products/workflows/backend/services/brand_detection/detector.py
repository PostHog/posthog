from collections.abc import Callable

from posthog.dataclasses import frozen

from products.workflows.backend.services.brand_detection.files import (
    TreeEntry,
    UnknownAppRoot,
    choose_app_root,
    select_files,
)
from products.workflows.backend.services.brand_detection.logos import LogoCandidate, rank_logo_candidates
from products.workflows.backend.services.brand_detection.proposal import BrandCandidates, BrandProposal, rank_signals
from products.workflows.backend.services.brand_detection.signals import (
    Signal,
    SignalKind,
    VariableTable,
    extract_signals,
)

__all__ = ["BrandDetection", "TreeEntry", "UnknownAppRoot", "detect_brand"]

ReadText = Callable[[str], str | None]

FIELD_OF_KIND = {
    SignalKind.MANIFEST_NAME: "name",
    SignalKind.SITE_NAME: "name",
    SignalKind.MANIFEST_SHORT_NAME: "name",
    SignalKind.METADATA_TITLE: "name",
    SignalKind.HTML_TITLE: "name",
    SignalKind.PACKAGE_NAME: "name",
    SignalKind.BRAND_TOKEN: "primary_color",
    SignalKind.PRIMARY_TOKEN: "primary_color",
    SignalKind.THEME_COLOR: "primary_color",
    SignalKind.LOGO_FILL: "primary_color",
    SignalKind.ACCENT_TOKEN: "accent_color",
    SignalKind.TEXT_TOKEN: "text_color",
    SignalKind.BACKGROUND_TOKEN: "background_color",
    SignalKind.NEXT_FONT: "font_family",
    SignalKind.CSS_FONT_SANS: "font_family",
    SignalKind.TAILWIND_FONT_SANS: "font_family",
    SignalKind.BODY_FONT_FAMILY: "font_family",
    SignalKind.GOOGLE_FONTS_LINK: "font_family",
}


@frozen
class FoundValue:
    field: str
    value: str


@frozen
class FileRead:
    path: str
    found: tuple[FoundValue, ...]


@frozen
class BrandDetection:
    """A proposed Email brand with where each value came from. Detection never saves it."""

    repository: str
    app_root: str
    app_root_alternatives: tuple[str, ...]
    proposal: BrandProposal
    candidates: BrandCandidates
    logo_candidates: tuple[LogoCandidate, ...]
    files_read: tuple[FileRead, ...]


def detect_brand(
    *, repository_name: str, tree: list[TreeEntry], read_text: ReadText, app_root: str | None = None
) -> BrandDetection:
    """Read the brand files of ``tree`` through ``read_text`` and propose an Email brand from their signals.

    ``read_text`` returns a file's text, or None to skip a file it could not read in time.
    Raises ``UnknownAppRoot`` when ``app_root`` names no directory of the tree.
    """
    choice = choose_app_root(tree, app_root)
    texts = _read_texts(select_files(tree, choice.root), read_text)
    variables = VariableTable.from_style_files(texts)
    signals_by_path = {path: extract_signals(path, text, variables) for path, text in texts.items()}
    proposal, candidates = rank_signals(
        [signal for signals in signals_by_path.values() for signal in signals], repository_name
    )
    return BrandDetection(
        repository=repository_name,
        app_root=choice.root,
        app_root_alternatives=choice.alternatives,
        proposal=proposal,
        candidates=candidates,
        logo_candidates=rank_logo_candidates(tree, choice.root, texts),
        files_read=tuple(
            FileRead(path=path, found=_found_values(signals)) for path, signals in signals_by_path.items()
        ),
    )


def _read_texts(paths: list[str], read_text: ReadText) -> dict[str, str]:
    texts = {}
    for path in paths:
        text = read_text(path)
        if text is not None:
            texts[path] = text
    return texts


def _found_values(signals: list[Signal]) -> tuple[FoundValue, ...]:
    found = [FoundValue(field=FIELD_OF_KIND[signal.kind], value=signal.value) for signal in signals]
    return tuple(dict.fromkeys(found))
