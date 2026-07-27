"""Self-driving surface: which products a Signals scout watches, and which ship skills.

**Open world today.** Scouts declare the product they cover via `metadata.scope` in their
SKILL.md frontmatter, but eleven scopes (`apm`, `web_vitals`, `csp_violations`, …) do not
name any product directory. `apm` almost certainly covers `products/tracing` — but the
repo does not say so, and inferring it would be a guess. While any scope is unattributed,
absence of a scout is not evidence of absence, so products with no scout get `unknown`
rather than `unavailable`.

The world closes itself: once every scope resolves, this source starts emitting
`unavailable`, with no rule change needed.
"""

from __future__ import annotations

import re

import yaml

from ..context import DerivationContext
from ..models import SurfaceFact

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

_SCOUT_GLOB_DIR = "products/signals/skills"
_SCOUT_PREFIX = "signals-scout-"


def _frontmatter(text: str) -> dict:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    parsed = yaml.safe_load(match.group(1))
    return parsed if isinstance(parsed, dict) else {}


def _scout_scopes(ctx: DerivationContext) -> list[tuple[str, str, str | None]]:
    """(scout_name, relpath, scope) for every canonical scout, scope may be None."""
    root = ctx.repo_root / _SCOUT_GLOB_DIR
    if not root.is_dir():
        return []

    found: list[tuple[str, str, str | None]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not entry.name.startswith(_SCOUT_PREFIX):
            continue
        skill = entry / "SKILL.md"
        if not skill.exists():
            continue
        metadata = _frontmatter(skill.read_text()).get("metadata") or {}
        scope = metadata.get("scope") if isinstance(metadata, dict) else None
        found.append((entry.name, ctx.rel(skill), scope if isinstance(scope, str) else None))
    return found


def unattributed_scopes(ctx: DerivationContext) -> list[str]:
    """Scout scopes that name no product directory. Surfaced verbatim at the top level."""
    return sorted({scope for _name, _rel, scope in _scout_scopes(ctx) if scope and ctx.join(scope).product is None})


def derive(ctx: DerivationContext) -> dict[str, SurfaceFact]:
    scouts = _scout_scopes(ctx)
    world_is_open = bool(unattributed_scopes(ctx))

    by_product: dict[str, list[tuple[str, str, str]]] = {}
    for name, rel, scope in scouts:
        if not scope:
            continue
        join = ctx.join(scope)
        if join.product is None:
            continue
        by_product.setdefault(join.product, []).append((name, rel, join.match))

    results: dict[str, SurfaceFact] = {}
    for product in sorted(ctx.product_dirs):
        scout_entries = by_product.get(product, [])
        skills_dir = ctx.products_dir / product / "skills"
        skill_names = (
            sorted(d.name for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists())
            if skills_dir.is_dir()
            else []
        )

        sources = [rel for _n, rel, _m in scout_entries]
        if skill_names:
            sources.append(f"products/{product}/skills/")

        if scout_entries or skill_names:
            results[product] = SurfaceFact(
                availability="available",
                facts={
                    "scouts": sorted(n for n, _r, _m in scout_entries),
                    "scout_match": sorted({m for _n, _r, m in scout_entries}),
                    "skills": skill_names,
                },
                **{"from": sources},
            )
        elif world_is_open:
            results[product] = SurfaceFact(
                availability="unknown",
                unknown_reason=(
                    "scout attribution is incomplete — some scout scopes name no product "
                    "directory, so the absence of a scout does not prove the absence of coverage"
                ),
            )
        else:
            results[product] = SurfaceFact(
                availability="unavailable",
                facts={"scouts": [], "skills": []},
                **{"from": [f"{_SCOUT_GLOB_DIR}/", f"products/{product}/"]},
            )

    return results
