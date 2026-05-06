"""TypeScript helpers for analyzing frontend code generation adoption."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_EXPORTED_ASYNC_RE = re.compile(r"^export\s+const\s+(\w+)\s*=\s*async\s*\(", re.MULTILINE)


def get_generated_endpoint_names(generated_api_ts: Path) -> list[str]:
    """Return names of generated endpoint functions in a product's generated/api.ts."""
    if not generated_api_ts.exists():
        return []
    content = generated_api_ts.read_text()
    return _EXPORTED_ASYNC_RE.findall(content)


def get_generated_imports_in_frontend(frontend_dir: Path) -> set[str]:
    """Find which generated endpoint function names are imported in frontend code.

    Scans all .ts/.tsx files in the product's frontend/ directory, excluding the
    generated/ subdirectory itself. Returns the set of imported function names.
    """
    generated_dir = frontend_dir / "generated"
    imported: set[str] = set()

    for ts_file in _collect_ts_files(frontend_dir):
        if _is_inside(ts_file, generated_dir):
            continue
        content = ts_file.read_text()
        # Match: import { funcA, funcB } from '...generated/api'
        # We first collapse the file into single-line imports so multi-line
        # imports like:
        #   import {
        #     funcA,
        #     funcB,
        #   } from '../generated/api'
        # are handled correctly.
        collapsed = re.sub(r"\n\s*", " ", content)
        for match in re.finditer(
            r"import\s*\{([^}]+)\}\s*from\s*['\"][^'\"]*generated/api['\"]",
            collapsed,
        ):
            names = [n.strip().split(" as ")[0].strip() for n in match.group(1).split(",")]
            imported.update(n for n in names if n and not n.startswith("type "))

        # Also match: import type { ... } from '...generated/api.schemas'
        # These are type-only imports and don't count as endpoint usage.
        # (We deliberately skip them.)

    return imported


_HTTP_VERBS = re.compile(r"\bapi\.(?:get|post|put|patch|delete|create|update)\s*(?:<[^>]*>)?\s*\(", re.IGNORECASE)
_HTTP_VERBS_WITH_URL = re.compile(
    r"\bapi\.(get|post|put|patch|delete|create|update)\s*(?:<[^>]*>)?\s*\(\s*[`'\"](.*?)[`'\"]",
    re.IGNORECASE,
)

_VERB_TO_METHOD = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
    "create": "POST",
    "update": "PUT",
}


def count_manual_api_calls(frontend_dir: Path) -> int:
    """Count manual HTTP calls via the shared api object.

    Only counts direct HTTP verb calls: api.get(, api.post(, api.create(,
    api.update(, api.delete(, api.patch(, api.put(.

    Does NOT count api.<namespace>.<method>( — those are shared platform
    utilities (api.integrations.authorizeUrl, api.comments.create, etc.)
    that belong to other products and aren't replaceable by this product's
    generated client.
    """
    generated_dir = frontend_dir / "generated"
    total = 0

    for ts_file in _collect_ts_files(frontend_dir):
        if _is_inside(ts_file, generated_dir):
            continue
        content = ts_file.read_text()
        has_api_import = (
            "from 'lib/api'" in content
            or 'from "lib/api"' in content
            or "from '~/lib/api'" in content
            or 'from "~/lib/api"' in content
        )
        if not has_api_import:
            continue
        total += len(_HTTP_VERBS.findall(content))

    return total


def codegen_adoption(frontend_dir: Path) -> dict:
    """Compute code generation adoption metrics for a product's frontend.

    Returns a dict with:
        generated_available: number of generated endpoint functions
        generated_used: number actually imported in product frontend code
        manual_calls: number of manual api.* calls
        adoption_ratio: float 0-1, or None if no API usage at all
    """
    generated_api = frontend_dir / "generated" / "api.ts"
    available = get_generated_endpoint_names(generated_api)
    used = get_generated_imports_in_frontend(frontend_dir)

    # Only count imports that match available generated functions
    used_valid = used & set(available)

    manual = count_manual_api_calls(frontend_dir)

    total_usage = len(used_valid) + manual
    adoption_ratio = len(used_valid) / total_usage if total_usage > 0 else None

    return {
        "generated_available": len(available),
        "generated_used": len(used_valid),
        "manual_calls": manual,
        "adoption_ratio": adoption_ratio,
    }


# ---------------------------------------------------------------------------
# Detailed call-site analysis with generated equivalent matching
# ---------------------------------------------------------------------------


@dataclass
class ManualCallSite:
    file: str
    line: int
    verb: str
    url: str
    method: str
    generated_equivalent: str | None


def _normalize_url(url: str) -> str:
    """Normalize a URL for comparison: replace template vars, strip query params."""
    url = re.sub(r"\$\{[^}]+\}", "{p}", url)
    url = re.sub(r"@current", "{p}", url)
    url = re.sub(r"\?.*", "", url)
    url = url.rstrip("/")
    if not url.startswith("/"):
        url = "/" + url
    return url


def _parse_generated_url_map(api_ts: Path) -> dict[tuple[str, str], str]:
    """Parse generated/api.ts and return {(normalized_url, METHOD): function_name}."""
    if not api_ts.exists():
        return {}
    content = api_ts.read_text()

    # Extract URL helpers — handle both simple return and ternary (query param variants)
    url_helpers: dict[str, str] = {}
    for m in re.finditer(
        r"export const (get\w+Url)\s*=\s*\([^)]*\)\s*(?::\s*\w+\s*)?=>\s*\{(.*?)\n\}",
        content,
        re.DOTALL,
    ):
        name = m.group(1)
        body = m.group(2)
        urls = re.findall(r"[`]([^`]+)[`]", body)
        if urls:
            # Prefer the URL without query params (cleaner for matching)
            clean = [u for u in urls if "?" not in u] or urls
            url_helpers[name] = clean[0]

    # Map async functions to their URL + method
    generated: dict[tuple[str, str], str] = {}
    for m in re.finditer(
        r"export const (\w+)\s*=\s*async\s*\(.*?method:\s*['\"](\w+)['\"]",
        content,
        re.DOTALL,
    ):
        fn_name = m.group(1)
        method = m.group(2)
        fn_text = content[m.start() : m.start() + 500]
        url_call = re.search(r"(get\w+Url)\(", fn_text)
        if url_call and url_call.group(1) in url_helpers:
            raw_url = url_helpers[url_call.group(1)]
            url = _normalize_url(raw_url)
            generated[(url, method)] = fn_name

    return generated


def codegen_call_sites(frontend_dir: Path) -> list[ManualCallSite]:
    """Find all manual API call sites and match them to generated equivalents.

    Returns a list of ManualCallSite objects with file, line, verb, url,
    and the matched generated function name (or None if no match).
    """
    api_ts = frontend_dir / "generated" / "api.ts"
    generated_map = _parse_generated_url_map(api_ts)
    generated_dir = frontend_dir / "generated"

    sites: list[ManualCallSite] = []

    for ts_file in _collect_ts_files(frontend_dir):
        if _is_inside(ts_file, generated_dir):
            continue
        content = ts_file.read_text()
        has_api_import = (
            "from 'lib/api'" in content
            or 'from "lib/api"' in content
            or "from '~/lib/api'" in content
            or 'from "~/lib/api"' in content
        )
        if not has_api_import:
            continue

        rel_path = str(ts_file.relative_to(frontend_dir))

        # Match verb + URL across lines (URL may be on the next line)
        multi_line_re = re.compile(
            r"\bapi\.(get|post|put|patch|delete|create|update)\s*(?:<[^>]*>)?\s*\(\s*[`'\"](.*?)[`'\"]",
            re.IGNORECASE | re.DOTALL,
        )
        for m in multi_line_re.finditer(content):
            verb = m.group(1).lower()
            raw_url = m.group(2)
            # Compute line number from offset
            line_no = content[: m.start()].count("\n") + 1
            method = _VERB_TO_METHOD[verb]
            url = _normalize_url(raw_url)
            equivalent = generated_map.get((url, method))
            sites.append(
                ManualCallSite(
                    file=rel_path,
                    line=line_no,
                    verb=verb,
                    url=raw_url,
                    method=method,
                    generated_equivalent=equivalent,
                )
            )

    return sites


def _collect_ts_files(directory: Path) -> list[Path]:
    """Collect .ts and .tsx files, skipping node_modules and __pycache__."""
    if not directory.exists():
        return []
    return [
        f
        for f in directory.rglob("*.ts*")
        if f.suffix in (".ts", ".tsx") and "node_modules" not in f.parts and "__pycache__" not in f.parts
    ]


def _is_inside(path: Path, parent: Path) -> bool:
    """Check if path is inside parent directory."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
