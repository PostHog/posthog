"""TypeScript helpers for analyzing frontend code generation adoption."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from hogli_commands.api_ratchet import NamespaceMember, namespace_members, namespaces_owned_by

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

    Recognizes both named and namespace imports:
        import { funcA, funcB } from '../generated/api'
        import * as api from '../generated/api'   // then any `api.funcA` usage
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

        # Match: import * as <alias> from '...generated/api'
        # Tree-shaken namespace imports — collect every `<alias>.<member>`
        # access. Non-endpoint members (e.g. URL helpers) are filtered later
        # against the known endpoint names.
        for match in re.finditer(
            r"import\s*\*\s*as\s+(\w+)\s*from\s*['\"][^'\"]*generated/api['\"]",
            collapsed,
        ):
            alias = match.group(1)
            usage_re = re.compile(rf"\b{re.escape(alias)}\.(\w+)")
            for usage in usage_re.finditer(content):
                imported.add(usage.group(1))

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


def owned_namespace_pattern(frontend_dir: Path) -> re.Pattern[str] | None:
    """Regex over `api.<namespace>.<method>(` for the namespaces this product owns.

    A namespace counts as owned when an `ApiRequest` path method behind it builds
    a URL this product's generated client already emits, which `lint:api-ratchet`
    decides. Returns None when the product owns none.
    """
    owned = namespaces_owned_by(frontend_dir.parent.name)
    if not owned:
        return None
    alternatives = "|".join(sorted(owned))
    # `(?:\s*\.\s*\w+)+` so a nested chain (api.signalScout.runs.list) counts once, and
    # a call the formatter broke across lines (api.endpoint\n    .get(...)) counts at all.
    return re.compile(rf"\bapi\.({alternatives})((?:\s*\.\s*\w+)+)\s*(?:<[^(]*>)?\s*\(")


def count_manual_api_calls(frontend_dir: Path) -> int:
    """Count manual API calls via the shared api object.

    Counts direct HTTP verb calls (api.get(, api.post(, api.create(, ...) and
    `api.<namespace>.<method>(` where the namespace belongs to this product -
    the generated client already covers those URLs, so they are this product's
    debt. A namespace owned by another product, or by none, is not counted:
    api.comments.create is not this product's call to migrate.
    """
    generated_dir = frontend_dir / "generated"
    namespaced = owned_namespace_pattern(frontend_dir)
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
        if namespaced is not None:
            total += len(namespaced.findall(content))

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
    # A call on a namespace this product owns whose route and verb the generated client
    # covers. False when the client has no operation for it, which is a backend gap.
    namespaced: bool = False
    # Why a site has no generated function, when the reason is not a missing endpoint.
    note: str = ""


def _generated_key(request: NamespaceMember) -> str:
    """The member's route in the shape `_parse_generated_url_map` keys on."""
    return "/api/" + "/".join("{p}" if segment == "{}" else segment for segment in request.template)


def _candidate_functions(request: NamespaceMember, generated_map: dict[tuple[str, str], str]) -> list[str]:
    """Generated functions whose route fits the member's route, holes as wildcards.

    A member that takes a path segment from its caller
    (api.errorTracking.createRule(ErrorTrackingRuleType.Bypass, ...)) builds a mask
    rather than one route, and the client generates a function per concrete segment.
    `_narrow_by_arguments` picks between the survivors using the call's own tokens.
    """
    mask = _generated_key(request).split("/")
    fitting: dict[str, list[str]] = {}
    for (url, method), name in generated_map.items():
        if method != request.method:
            continue
        segments = url.split("/")
        if len(segments) != len(mask):
            continue
        if all(want in {have, "{p}"} for want, have in zip(mask, segments)):
            fitting[name] = segments
    if not fitting:
        return []
    # A mask hole can be a real id or a resource-type selector - the mask alone can't
    # say which. But when some candidate does vary by id in that spot, a literal
    # action route sharing the spot (`.../reorder/`) is a different operation, not
    # this one with an id, so it drops out rather than passing as an ambiguous match.
    if mask[-1] == "{p}" and any(segments[-1] == "{p}" for segments in fitting.values()):
        fitting = {name: segments for name, segments in fitting.items() if segments[-1] == "{p}"}
    return sorted(fitting)


def _first_call_argument(arguments: str) -> str:
    """The text of a call's first argument, up to its own top-level comma."""
    depth = 0
    for index, char in enumerate(arguments):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            return arguments[:index]
    return arguments


def _narrow_by_arguments(candidates: list[str], arguments: str) -> list[str]:
    """The candidates the call's selector argument names, or all of them.

    The route the member's own path method builds takes its dynamic segment from the
    first argument (`errorTrackingRule(ruleType, id)`) - later arguments are the
    entity id or payload, not the selector, and a token from one of those
    (`values.rule.id`) can match every candidate's shared `Rule`/`Rules` suffix and
    defeat the narrowing entirely. `ErrorTrackingRuleType.Bypass` and `'bypass_rules'`
    both name the bypass route, so the token after the last dot or inside the quotes
    picks the function.
    """
    selector = _first_call_argument(arguments)
    tokens = [
        token.lower()
        for token in re.findall(r"""['"`](\w+)['"`]|\.(\w+)|\b([A-Z]\w+)""", selector)
        for token in token
        if token
    ]
    named = [name for name in candidates if any(token in name.lower() for token in tokens)]
    return named or candidates


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
        # The last helper call before the method, rather than the first in a fixed
        # window: a function that builds a FormData first pushes the call past 500
        # characters, and the helper always sits on the line that sends the request.
        url_calls = re.findall(r"(get\w+Url)\(", m.group(0))
        if url_calls and url_calls[-1] in url_helpers:
            raw_url = url_helpers[url_calls[-1]]
            url = _normalize_url(raw_url)
            generated[(url, method)] = fn_name

    return generated


def _read_arguments(content: str, open_paren: int) -> str:
    """The argument text of the call whose `(` sits at ``open_paren``."""
    depth = 0
    for index in range(open_paren, len(content)):
        if content[index] == "(":
            depth += 1
        elif content[index] == ")":
            depth -= 1
            if depth == 0:
                return content[open_paren + 1 : index]
    return ""


def _resolve_namespaced(
    request: NamespaceMember | None,
    content: str,
    open_paren: int,
    generated_map: dict[tuple[str, str], str],
) -> tuple[str | None, str]:
    """The generated function for a namespaced call site, and why there is none."""
    if request is None:
        return None, ""
    if not request.method:
        return None, f"unrecognized transport: api.{request.transport}"
    exact = generated_map.get((_generated_key(request), request.method))
    if exact is not None:
        return exact, ""
    candidates = _candidate_functions(request, generated_map)
    if not candidates:
        return None, ""
    named = _narrow_by_arguments(candidates, _read_arguments(content, open_paren))
    return (named[0] if len(named) == 1 else " | ".join(named)), ""


def codegen_call_sites(frontend_dir: Path) -> list[ManualCallSite]:
    """Find all manual API call sites and match them to generated equivalents.

    Returns a list of ManualCallSite objects with file, line, verb, url, and the
    matched generated function name (or None if no match). A call on a namespace
    this product owns carries no URL at the call site, so it names the client that
    covers it instead of a function.
    """
    api_ts = frontend_dir / "generated" / "api.ts"
    generated_map = _parse_generated_url_map(api_ts)
    generated_dir = frontend_dir / "generated"
    namespaced = owned_namespace_pattern(frontend_dir)
    # Built once for the whole report: it parses all of lib/api.ts, and a product with
    # many files importing it would otherwise repeat that parse once per file.
    members = namespace_members() if namespaced is not None else {}

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

        if namespaced is None:
            continue
        for m in namespaced.finditer(content):
            namespace = m.group(1)
            member = re.sub(r"\s+", "", m.group(2)).lstrip(".")
            # The route and verb the namespace method sends, so a member the client has
            # no operation for is reported as a gap rather than as already covered.
            request = members.get(f"{namespace}.{member}")
            equivalent, note = _resolve_namespaced(request, content, m.end() - 1, generated_map)
            sites.append(
                ManualCallSite(
                    file=rel_path,
                    line=content[: m.start()].count("\n") + 1,
                    verb=f"{namespace}.{member}",
                    url="/".join(request.template) if request is not None else "",
                    method=request.method if request is not None else "",
                    generated_equivalent=equivalent,
                    namespaced=equivalent is not None,
                    note=note,
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
