"""Repo scan — the one file-IO edge of the detector.

Walks the scan targets under a ``repo_root`` and applies the pure ``extract_usages`` to each file.
Kept thin so the logic it delegates to stays unit-testable without a filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass
from glob import glob
from pathlib import Path

from products.signals.backend.api_deprecation.extractors import extract_usages
from products.signals.backend.api_deprecation.schema import ApiUsage


@dataclass(frozen=True)
class ScanTarget:
    """A file glob plus how its code is deployed — which decides what a fix entails."""

    file_glob: str
    # True if matched code is compiled into persisted rows (CDP templates bake into
    # HogFunction.hog), so a fix needs a data migration on top of the source change.
    persisted_per_row: bool


# The repo's third-party integration surfaces.
DEFAULT_SCAN_TARGETS: tuple[ScanTarget, ...] = (
    # CDP destination templates (both trees) — compiled into per-customer HogFunction rows.
    ScanTarget("nodejs/src/cdp/templates/_destinations/**/*.template.ts", persisted_per_row=True),
    ScanTarget("posthog/cdp/templates/**/*.py", persisted_per_row=True),
    # Data warehouse import sources (Stripe, Shopify, Recharge, …) — plain source code.
    ScanTarget("posthog/temporal/data_imports/sources/**/*.py", persisted_per_row=False),
    # Batch export destinations — mostly SDK-based, but URL call sites still surface here.
    ScanTarget("products/batch_exports/backend/**/*.py", persisted_per_row=False),
    # Native integrations (Slack/Google/LinkedIn OAuth endpoints, …).
    ScanTarget("posthog/models/integration.py", persisted_per_row=False),
)


def scan_repo(
    repo_root: str | Path,
    targets: tuple[ScanTarget, ...] = DEFAULT_SCAN_TARGETS,
    *,
    include_test_files: bool = False,
) -> list[ApiUsage]:
    """Return every external URL usage found under ``repo_root`` for the given targets.

    Test-file usages are excluded by default (precision: they must never drive remediation), but are
    still extractable via ``include_test_files=True`` for diagnostics.
    """
    root = Path(repo_root)
    usages: list[ApiUsage] = []
    seen_paths: set[str] = set()
    for target in targets:
        for absolute in glob(str(root / target.file_glob), recursive=True):
            rel = str(Path(absolute).relative_to(root))
            if rel in seen_paths:
                continue
            seen_paths.add(rel)
            try:
                text = Path(absolute).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            usages.extend(extract_usages(text, rel, persisted_per_row=target.persisted_per_row))

    if not include_test_files:
        usages = [usage for usage in usages if not usage.is_test_file]
    return usages
