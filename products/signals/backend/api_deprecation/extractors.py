"""Pin extraction — the repo-agnostic detection rules.

An extractor is a small declarative rule: confirm a vendor's host is present in a file, then pull
the literal version with one or more capture regexes. Adding a vendor (or supporting a new repo) is
adding an ``PinExtractor`` row — no changes to the scan/match logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from products.signals.backend.api_deprecation.schema import Pin


@dataclass(frozen=True)
class PinExtractor:
    vendor: str
    product: str
    host: str
    # Marker that confirms the vendor is referenced in a file before we try to extract a version.
    host_marker: str
    # Each regex must expose exactly one capture group = the version literal (e.g. "v21.0").
    # Multiple patterns cover the two ways versions appear: inline in the URL, or as a default
    # assigned to a version variable.
    version_patterns: tuple[str, ...]
    file_globs: tuple[str, ...]
    persisted_per_row: bool = True

    def compiled(self) -> tuple[re.Pattern[str], ...]:
        return tuple(re.compile(p) for p in self.version_patterns)


# First concrete adapters: Meta Graph + Google Ads, across both CDP template trees.
EXTRACTORS: tuple[PinExtractor, ...] = (
    PinExtractor(
        vendor="meta",
        product="Meta Graph API",
        host="graph.facebook.com",
        host_marker="graph.facebook.com",
        version_patterns=(
            r"graph\.facebook\.com/(v\d+\.\d+)",  # inline URL form (python meta_ads template)
            r"api_version[^\n]*?'(v\d+\.\d+)'",  # default-variable form (nodejs whatsapp template)
            r"apiVersion[^\n]*?'(v\d+\.\d+)'",
        ),
        file_globs=(
            "nodejs/src/cdp/templates/_destinations/**/*.template.ts",
            "posthog/cdp/templates/**/*.py",
        ),
    ),
    PinExtractor(
        vendor="google_ads",
        product="Google Ads API",
        host="googleads.googleapis.com",
        host_marker="googleads.googleapis.com",
        version_patterns=(r"googleads\.googleapis\.com/(v\d+)",),
        file_globs=(
            "nodejs/src/cdp/templates/_destinations/**/*.template.ts",
            "posthog/cdp/templates/**/*.py",
        ),
    ),
)


def is_test_path(file_path: str) -> bool:
    lowered = file_path.lower()
    return ".test." in lowered or "/test_" in lowered or lowered.endswith("_test.py") or "/tests/" in lowered


def extract_pins(file_text: str, file_path: str, extractor: PinExtractor) -> list[Pin]:
    """Pure: return the version pins an extractor finds in one file's text.

    Returns one ``Pin`` per distinct pinned version (first occurrence wins for the line number),
    so a file that repeats the same version on several lines yields a single pin.
    """
    if extractor.host_marker not in file_text:
        return []

    seen_versions: dict[str, int] = {}  # version -> 1-based line of first occurrence
    for pattern in extractor.compiled():
        for match in pattern.finditer(file_text):
            version = match.group(1)
            if version in seen_versions:
                continue
            line = file_text.count("\n", 0, match.start()) + 1
            seen_versions[version] = line

    return [
        Pin(
            vendor=extractor.vendor,
            product=extractor.product,
            host=extractor.host,
            pinned_version=version,
            file=file_path,
            line=line,
            extractor=extractor.vendor,
            is_test_file=is_test_path(file_path),
            persisted_per_row=extractor.persisted_per_row,
        )
        for version, line in sorted(seen_versions.items(), key=lambda kv: kv[1])
    ]
