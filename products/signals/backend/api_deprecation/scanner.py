"""Repo scan — the one file-IO edge of the detector.

Walks ``file_globs`` under a ``repo_root`` and applies the pure ``extract_usages`` to each file.
Kept thin so the logic it delegates to stays unit-testable without a filesystem.
"""

from __future__ import annotations

from glob import glob
from pathlib import Path

from products.signals.backend.api_deprecation.extractors import extract_usages
from products.signals.backend.api_deprecation.schema import ApiUsage

# Where third-party API calls live today: the CDP destination template trees. Both trees compile
# template code into persisted HogFunction rows, hence ApiUsage.persisted_per_row defaulting True.
DEFAULT_FILE_GLOBS: tuple[str, ...] = (
    "nodejs/src/cdp/templates/_destinations/**/*.template.ts",
    "posthog/cdp/templates/**/*.py",
)


def scan_repo(
    repo_root: str | Path,
    file_globs: tuple[str, ...] = DEFAULT_FILE_GLOBS,
    *,
    include_test_files: bool = False,
) -> list[ApiUsage]:
    """Return every external URL usage found under ``repo_root`` for the given globs.

    Test-file usages are excluded by default (precision: they must never drive remediation), but are
    still extractable via ``include_test_files=True`` for diagnostics.
    """
    root = Path(repo_root)
    usages: list[ApiUsage] = []
    seen_paths: set[str] = set()
    for pattern in file_globs:
        for absolute in glob(str(root / pattern), recursive=True):
            rel = str(Path(absolute).relative_to(root))
            if rel in seen_paths:
                continue
            seen_paths.add(rel)
            try:
                text = Path(absolute).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            usages.extend(extract_usages(text, rel))

    if not include_test_files:
        usages = [usage for usage in usages if not usage.is_test_file]
    return usages
