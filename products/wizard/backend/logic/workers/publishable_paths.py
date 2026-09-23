import shlex
from collections.abc import Iterable, Sequence
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

_ENV_TEMPLATE_SUFFIXES = {".dist", ".example", ".sample", ".template"}
_EXCLUDED_DIRECTORIES = {
    ".agents",
    ".aws",
    ".azure",
    ".claude",
    ".codex",
    ".docker",
    ".cursor",
    ".gemini",
    ".gnupg",
    ".kube",
    ".m2",
    ".opencode",
    ".skills",
    ".ssh",
    ".windsurf",
}
_EXCLUDED_UNTRACKED_DIRECTORIES = {
    ".astro",
    ".cache",
    ".mypy_cache",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".ruff_cache",
    ".svelte-kit",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "logs",
    "node_modules",
    "venv",
}
_EXCLUDED_FILES = {
    ".cursorrules",
    ".dev.vars",
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".windsurfrules",
    "agents.md",
    "claude.md",
    "gemini.md",
    "skill.md",
    "skills-lock.json",
    "secrets.toml",
}
_EXCLUDED_CHILDREN = {
    ".config": {"gcloud"},
    ".github": {"copilot-instructions.md", "instructions", "prompts", "skills"},
}
_EXCLUDED_FILE_PATTERNS = (
    "*.env.local",
    "*.env.*.local",
    "*.jks",
    "*.key",
    "*.keystore",
    "*.p12",
    "*.pem",
    "*.pfx",
    "*.sqlite",
    "*.sqlite3",
    "*.tfstate",
    "*.tfstate.*",
    "id_ed25519*",
    "id_dsa*",
    "id_ecdsa*",
    "id_rsa*",
    "service*account*.json",
)


def select_publishable_paths(tracked_paths: Iterable[str], untracked_paths: Iterable[str]) -> tuple[str, ...]:
    tracked = (path for path in tracked_paths if _is_publishable_path(path, untracked=False))
    untracked = (path for path in untracked_paths if _is_publishable_path(path, untracked=True))
    return tuple(sorted(set(tracked) | set(untracked)))


def literal_git_pathspec(paths: Sequence[str]) -> str:
    return shlex.join(f":(top,literal){path}" for path in paths)


def _is_publishable_path(path: str, *, untracked: bool) -> bool:
    parsed = PurePosixPath(path)
    if not parsed.parts or parsed.is_absolute() or ".." in parsed.parts:
        return False

    parts = tuple(part.casefold() for part in parsed.parts)
    if any(part in _EXCLUDED_DIRECTORIES for part in parts):
        return False
    if untracked and any(part in _EXCLUDED_UNTRACKED_DIRECTORIES for part in parts[:-1]):
        return False
    if any(child in _EXCLUDED_CHILDREN.get(parent, ()) for parent, child in zip(parts, parts[1:])):
        return False

    name = parts[-1]
    if name in _EXCLUDED_FILES or _is_private_environment_file(name):
        return False
    return not any(fnmatchcase(name, pattern) for pattern in _EXCLUDED_FILE_PATTERNS)


def _is_private_environment_file(name: str) -> bool:
    if PurePosixPath(name).suffix in _ENV_TEMPLATE_SUFFIXES:
        return False
    return name == ".envrc" or name == ".env" or name.startswith(".env.") or name.endswith(".env")
