"""Usage extraction — the repo-agnostic detection rules.

The detector inventories every external ``https://`` URL in the scanned files — API call sites,
documentation links, OAuth scope identifiers alike. It deliberately does NOT judge which usages are
"real" third-party API calls: that triage is the research agent's first job (it can open the code),
and an inclusive inventory means a new destination's API is detected the moment its template lands,
with no per-vendor rules to maintain.

URLs are consumed with a small brace-aware scanner rather than a single regex: Hog f-string
interpolations may contain nested quotes (``f'…/customers/{splitByString('/', inputs.customerId)[1]}:uploadClickConversions'``)
and the endpoint name after the interpolation is exactly what endpoint-level deprecation research
needs. Interpolations are collapsed to ``{…}`` so endpoints are stable across runs — the inventory
hash drives in-flight run dedup.

The one remaining per-vendor concept is ``VariableVersionRule``: a version literal that lives in a
variable instead of the URL (WhatsApp's ``apiVersion`` default) is attached to the host's usages in
the same file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from products.signals.backend.api_deprecation.schema import ApiUsage

# Hosts that are ours (or doc placeholders) — never a third-party API usage.
IGNORED_HOST_SUFFIXES: tuple[str, ...] = ("posthog.com", "example.com")

_URL_START_RE = re.compile(r"https://([a-z0-9][a-z0-9.-]*\.[a-z]{2,})", re.IGNORECASE)
_VERSION_SEGMENT_RE = re.compile(r"^v\d+(?:\.\d+)*$")
_COMMENT_PREFIXES = ("//", "#", "*", "/*", "<!--")
_INTERPOLATION_PLACEHOLDER = "{…}"
_MAX_ENDPOINT_LENGTH = 160


@dataclass(frozen=True)
class VariableVersionRule:
    """Attach a version pinned in a variable (not the URL) to a host's usages in the same file."""

    host_marker: str
    # Each regex must expose exactly one capture group = the version literal (e.g. "v21.0").
    version_patterns: tuple[str, ...]

    def find_version(self, file_text: str) -> str | None:
        for pattern in self.version_patterns:
            match = re.search(pattern, file_text)
            if match:
                return match.group(1)
        return None


VARIABLE_VERSION_RULES: tuple[VariableVersionRule, ...] = (
    # Meta Graph templates default the version into an api_version/apiVersion input.
    VariableVersionRule(
        host_marker="graph.facebook.com",
        version_patterns=(r"api_version[^\n]*?'(v\d+\.\d+)'", r"apiVersion[^\n]*?'(v\d+\.\d+)'"),
    ),
)


def is_test_path(file_path: str) -> bool:
    lowered = file_path.lower()
    return ".test." in lowered or "/test_" in lowered or lowered.endswith("_test.py") or "/tests/" in lowered


def _is_ignored_host(host: str) -> bool:
    return any(host == suffix or host.endswith("." + suffix) for suffix in IGNORED_HOST_SUFFIXES)


def _consume_endpoint(line: str, start: int) -> str:
    """Consume a URL path starting at ``start``, collapsing each ``{…}`` interpolation.

    Tracks brace depth so interpolations containing quotes/parens don't truncate the path — the
    characters after an interpolation (e.g. ``:uploadClickConversions``) are load-bearing.
    """
    out: list[str] = []
    depth = 0
    i = start
    while i < len(line):
        ch = line[i]
        if depth == 0:
            if ch in " \t'\"`<>\\":
                break
            if ch == "}":  # closing an outer template literal — the URL ended before it
                break
            if ch == "{":
                depth = 1
                out.append(_INTERPOLATION_PLACEHOLDER)
            else:
                out.append(ch)
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    endpoint = "".join(out).split("?")[0]
    # Trailing punctuation is prose/markup around the URL, not path: "(see https://x.com/docs)."
    return endpoint.rstrip(".,;:)]")[:_MAX_ENDPOINT_LENGTH]


def _version_from_endpoint(endpoint: str) -> str | None:
    for segment in endpoint.split("/"):
        if _VERSION_SEGMENT_RE.match(segment):
            return segment
    return None


def extract_usages(
    file_text: str,
    file_path: str,
    variable_version_rules: tuple[VariableVersionRule, ...] = VARIABLE_VERSION_RULES,
) -> list[ApiUsage]:
    """Pure: return the distinct external URL usages in one file's text.

    One ``ApiUsage`` per distinct (host, endpoint, version) — first occurrence wins the line number.
    Comment-only lines are skipped; everything else (including doc links in input descriptions) is
    inventoried and left for the research agent to triage.
    """
    seen: dict[tuple[str, str, str | None], tuple[int, str]] = {}  # key -> (line, extractor)
    for line_number, line in enumerate(file_text.splitlines(), start=1):
        if line.lstrip().startswith(_COMMENT_PREFIXES):
            continue
        for match in _URL_START_RE.finditer(line):
            host = match.group(1).lower()
            if _is_ignored_host(host):
                continue
            endpoint = _consume_endpoint(line, match.end())
            version = _version_from_endpoint(endpoint)
            extractor = "url"
            if version is None:
                for rule in variable_version_rules:
                    if rule.host_marker in host:
                        version = rule.find_version(file_text)
                        if version is not None:
                            extractor = "url+variable-version"
                        break
            key = (host, endpoint, version)
            if key not in seen:
                seen[key] = (line_number, extractor)

    return [
        ApiUsage(
            host=host,
            endpoint=endpoint,
            version=version,
            file=file_path,
            line=line,
            extractor=extractor,
            is_test_file=is_test_path(file_path),
        )
        for (host, endpoint, version), (line, extractor) in sorted(seen.items(), key=lambda kv: kv[1][0])
    ]
