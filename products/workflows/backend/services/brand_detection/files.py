import re
from enum import Enum

from posthog.dataclasses import frozen


class FileKind(Enum):
    PACKAGE = "package"
    MANIFEST = "manifest"
    TAILWIND_CONFIG = "tailwind_config"
    DOCUMENT = "document"
    STYLE = "style"
    THEME_MODULE = "theme_module"
    LOGO = "logo"


@frozen
class TreeEntry:
    """One file of the repository tree: its path from the repository root and its size in bytes."""

    path: str
    size: int


@frozen
class AppRootChoice:
    root: str
    alternatives: tuple[str, ...]


class UnknownAppRoot(ValueError):
    pass


MAX_FILE_READS = 15
MAX_FILE_BYTES = 400_000

APP_ROOT = re.compile(r"^(apps/[^/]+/|frontend/|client/|web/)")
SHARED_THEME_PACKAGE = re.compile(r"^packages/(?:ui|config|tailwind-config)/")
OTHER_PACKAGE = re.compile(r"^packages/")
PREFERRED_APP_NAMES = ("web", "app", "dashboard", "frontend", "builder")
PREFERRED_APP_BONUS = 5
EXCLUDED_DIRECTORIES = frozenset(
    {
        "docs",
        "storybook",
        "email",
        "emails",
        "example",
        "examples",
        "e2e",
        "test",
        "tests",
        "fixtures",
        "node_modules",
        "dist",
        "build",
        ".next",
        "vendor",
    }
)

MANIFEST = re.compile(r"(?:^|/)(?:manifest\.json|site\.webmanifest|manifest\.webmanifest)$")
TAILWIND_CONFIG = re.compile(r"(?:^|/)tailwind\.config\.(?:js|cjs|mjs|ts)$")
DOCUMENT = re.compile(
    r"(?:^|/)(?:index\.html|_document\.(?:tsx|jsx|js)|layout\.(?:tsx|jsx|js)|root\.tsx|_app\.(?:tsx|jsx))$"
)
STYLE = re.compile(r"\.(?:css|scss|sass|less)$")
STYLE_NAME = re.compile(
    r"(?:global|globals|app|main|index|theme|variables|vars|colors|tokens|base|style|styles|tailwind)", re.IGNORECASE
)
THEME_MODULE = re.compile(r"(?:^|/)(?:theme|colors|palette|tokens)(?:/index)?\.(?:ts|tsx|js|jsx)$", re.IGNORECASE)
OWN_LOGO_SVG = re.compile(r"(?:^|/)(?:public|static|assets)/(?:.+/)?(?:logo|logomark|brand)(?:[-_.][^/]*)?\.svg$")
THIRD_PARTY_DIRECTORY = re.compile(r"/(?:integrations?|providers?|partners?|customers?|sponsors?|vendors?)/")
LOGO_VARIANT = re.compile(r"(?:white|dark|inverse|mono)", re.IGNORECASE)

READS_PER_KIND = (
    (FileKind.PACKAGE, 2),
    (FileKind.MANIFEST, 2),
    (FileKind.TAILWIND_CONFIG, 2),
    (FileKind.DOCUMENT, 3),
    (FileKind.STYLE, 5),
    (FileKind.THEME_MODULE, 2),
    (FileKind.LOGO, 1),
)


def file_kind(path: str) -> FileKind | None:
    name = path.rsplit("/", 1)[-1]
    if name == "package.json":
        return FileKind.PACKAGE
    if MANIFEST.search(path):
        return FileKind.MANIFEST
    if TAILWIND_CONFIG.search(path):
        return FileKind.TAILWIND_CONFIG
    if DOCUMENT.search(path):
        return FileKind.DOCUMENT
    if STYLE.search(path) and STYLE_NAME.search(name):
        return FileKind.STYLE
    if THEME_MODULE.search(path):
        return FileKind.THEME_MODULE
    if OWN_LOGO_SVG.search(path) and not THIRD_PARTY_DIRECTORY.search(path) and not LOGO_VARIANT.search(name):
        return FileKind.LOGO
    return None


def choose_app_root(tree: list[TreeEntry], requested: str | None) -> AppRootChoice:
    ranked = _ranked_app_roots(tree)
    if requested is None:
        return AppRootChoice(root=ranked[0] if ranked else "", alternatives=tuple(ranked[1:]))
    root = _normalized_root(requested)
    if root and not any(entry.path.startswith(root) for entry in tree):
        raise UnknownAppRoot(f"No files under {root} in this repository.")
    return AppRootChoice(root=root, alternatives=tuple(other for other in ranked if other != root))


def select_files(tree: list[TreeEntry], app_root: str) -> list[str]:
    in_scope = sorted(
        (entry.path for entry in tree if entry.size <= MAX_FILE_BYTES and _in_scope(entry.path, app_root)),
        key=lambda path: (not path.startswith(app_root), _depth_below(path, app_root), path),
    )
    selected: list[str] = []
    for kind, limit in READS_PER_KIND:
        selected += [path for path in in_scope if file_kind(path) is kind][:limit]
    return selected[:MAX_FILE_READS]


def _ranked_app_roots(tree: list[TreeEntry]) -> list[str]:
    roots = {match.group(1) for entry in tree if (match := APP_ROOT.match(entry.path))}
    scores = {root: _app_root_score(root, tree) for root in roots if not _is_excluded(root)}
    return sorted(scores, key=lambda root: (-scores[root], root))


def _app_root_score(root: str, tree: list[TreeEntry]) -> int:
    brand_files = sum(1 for entry in tree if entry.path.startswith(root) and file_kind(entry.path) is not None)
    name = root.rstrip("/").rsplit("/", 1)[-1]
    return brand_files + (PREFERRED_APP_BONUS if name in PREFERRED_APP_NAMES else 0)


def _in_scope(path: str, app_root: str) -> bool:
    if _is_excluded(path):
        return False
    if SHARED_THEME_PACKAGE.match(path):
        return True
    if app_root:
        return path.startswith(app_root) or not (APP_ROOT.match(path) or OTHER_PACKAGE.match(path))
    return not OTHER_PACKAGE.match(path)


def _is_excluded(path: str) -> bool:
    directories = path.lower().split("/")[:-1]
    return any(directory in EXCLUDED_DIRECTORIES for directory in directories)


def _depth_below(path: str, app_root: str) -> int:
    return path.removeprefix(app_root).count("/")


def _normalized_root(requested: str) -> str:
    stripped = requested.strip().strip("/")
    return f"{stripped}/" if stripped else ""
