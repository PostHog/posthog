"""Repo scan — the one file-IO edge of the detector.

Walks the extractor globs under a ``repo_root`` and applies the pure ``extract_pins`` to each file.
Kept thin so the logic it delegates to stays unit-testable without a filesystem.
"""

from __future__ import annotations

from glob import glob
from pathlib import Path

from products.signals.backend.api_deprecation.extractors import EXTRACTORS, PinExtractor, extract_pins
from products.signals.backend.api_deprecation.schema import Pin


def scan_repo(
    repo_root: str | Path,
    extractors: tuple[PinExtractor, ...] = EXTRACTORS,
    *,
    include_test_files: bool = False,
) -> list[Pin]:
    """Return every version pin found under ``repo_root`` for the given extractors.

    Test-file pins are excluded by default (precision: they must never drive remediation), but are
    still extractable via ``include_test_files=True`` for diagnostics.
    """
    root = Path(repo_root)
    pins: list[Pin] = []
    for extractor in extractors:
        seen_paths: set[str] = set()
        for pattern in extractor.file_globs:
            for absolute in glob(str(root / pattern), recursive=True):
                rel = str(Path(absolute).relative_to(root))
                if rel in seen_paths:
                    continue
                seen_paths.add(rel)
                try:
                    text = Path(absolute).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                pins.extend(extract_pins(text, rel, extractor))

    if not include_test_files:
        pins = [pin for pin in pins if not pin.is_test_file]
    return pins
