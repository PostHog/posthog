import re
from collections.abc import Callable

from posthog.dataclasses import frozen

from products.messaging.backend.services.repository_brand.colors import is_near_gray, is_near_white, literal_color
from products.messaging.backend.services.repository_brand.files import (
    FileKind,
    TreeEntry,
    choose_app_root,
    file_kind,
    select_files,
)
from products.messaging.backend.services.repository_brand.logos import rank_logo_paths
from products.messaging.backend.services.repository_brand.signals import (
    Signal,
    SignalKind,
    VariableTable,
    extract_signals,
)

__all__ = ["TreeEntry", "RepositoryBrand", "detect_brand"]

NAME_KINDS = (
    SignalKind.MANIFEST_NAME,
    SignalKind.SITE_NAME,
    SignalKind.MANIFEST_SHORT_NAME,
    SignalKind.METADATA_TITLE,
    SignalKind.HTML_TITLE,
    SignalKind.PACKAGE_NAME,
)
PRIMARY_KINDS = (SignalKind.BRAND_TOKEN, SignalKind.PRIMARY_TOKEN, SignalKind.THEME_COLOR, SignalKind.LOGO_FILL)
PACKAGE_SCOPE = re.compile(r"^@([\w.-]+)/")
SCAFFOLD_PREFIXES = frozenset({"my", "create", "vite"})
NAME_AFFIXES = re.compile(r"[-_](?:monorepo|app|root|project)$")
GENERIC_NAMES = frozenset(
    {
        *("web", "app", "www", "frontend", "client", "dashboard", "root", "monorepo", "main", "site", "platform", "ui"),
        *("next", "nextjs", "react", "starter", "template", "repo", "workspace"),
    }
)
NOISY_TITLE = re.compile(
    r"sign in|sign up|log in|login|loading|home|untitled|404|create next app|create react app|react app"
    r"|vite(?: \+ react(?: \+ ts)?)?",
    re.IGNORECASE,
)
STRING_OR_BLOCK_COMMENT = re.compile(
    r"(\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)|/\*.*?(?:\*/|\Z)", re.DOTALL
)
COMMENTED_KINDS = (FileKind.STYLE, FileKind.TAILWIND_CONFIG, FileKind.THEME_MODULE)
TITLE_SEPARATOR = re.compile(r"\s+[|\-–—:·]\s+")
SHADCN_STOCK_PRIMARIES = frozenset(
    literal_color(expression)
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
)


@frozen
class RepositoryBrand:
    name: str | None
    primary_color: str | None
    logo_paths: tuple[str, ...]


def _title_case_slug(slug: str) -> str:
    return " ".join(word[:1].upper() + word[1:] for word in re.split(r"[-_\s]+", slug) if word)


def _package_brand_name(package_name: str) -> str | None:
    scope = PACKAGE_SCOPE.match(package_name)
    if scope and scope.group(1).lower() not in GENERIC_NAMES:
        return _title_case_slug(scope.group(1))
    slug = NAME_AFFIXES.sub("", PACKAGE_SCOPE.sub("", package_name))
    words = re.split(r"[-_\s]+", slug.lower())
    return None if slug.lower() in GENERIC_NAMES or words[0] in SCAFFOLD_PREFIXES else _title_case_slug(slug)


def _clean_name(signal: Signal) -> str | None:
    if signal.kind is SignalKind.PACKAGE_NAME:
        return _package_brand_name(signal.value)
    is_page_title = signal.kind in (SignalKind.METADATA_TITLE, SignalKind.HTML_TITLE)
    title = TITLE_SEPARATOR.split(signal.value)[0].strip() if is_page_title else signal.value
    noisy = is_page_title and NOISY_TITLE.fullmatch(title) is not None
    return None if not title or noisy or title.lower() in GENERIC_NAMES else title[:255]


def _without_code_comments(path: str, text: str) -> str:
    if file_kind(path) not in COMMENTED_KINDS:
        return text
    return STRING_OR_BLOCK_COMMENT.sub(lambda match: match.group(1) or " ", text)


def _is_brand_color(color: str) -> bool:
    return not is_near_white(color) and color not in SHADCN_STOCK_PRIMARIES


def detect_brand(
    *,
    repository_name: str,
    tree: list[TreeEntry],
    read_text: Callable[[str], str | None],
) -> RepositoryBrand:
    root = choose_app_root(tree)
    texts = {path: _without_code_comments(path, text) for path in select_files(tree, root) if (text := read_text(path))}
    variables = VariableTable.from_style_files(texts)
    signals = [signal for path, text in texts.items() for signal in extract_signals(path, text, variables)]
    names = sorted(
        (signal for signal in signals if signal.kind in NAME_KINDS),
        key=lambda signal: NAME_KINDS.index(signal.kind),
    )
    colors = sorted(
        (signal for signal in signals if signal.kind in PRIMARY_KINDS and _is_brand_color(signal.value)),
        key=lambda signal: (is_near_gray(signal.value), PRIMARY_KINDS.index(signal.kind)),
    )
    return RepositoryBrand(
        name=next(
            (name for signal in names if (name := _clean_name(signal))),
            _title_case_slug(repository_name.rsplit("/", 1)[-1]),
        ),
        primary_color=colors[0].value if colors else None,
        logo_paths=rank_logo_paths(tree, root, texts),
    )
