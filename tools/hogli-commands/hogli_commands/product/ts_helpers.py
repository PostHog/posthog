"""TypeScript helpers for analyzing frontend code generation adoption."""

from __future__ import annotations

import re
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


_HTTP_VERBS = re.compile(r"\bapi\.(?:get|post|put|patch|delete|create|update)\s*\(", re.IGNORECASE)


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
