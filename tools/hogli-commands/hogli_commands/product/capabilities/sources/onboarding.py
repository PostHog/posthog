"""Data source: which SDKs and platforms a product documents an install flow for.

In-app onboarding content lives at ``docs/onboarding/<kebab-product>/``, one TSX file per
SDK. "No directory means no onboarding flow" is only a valid inference while *every*
onboarding directory maps to a product — otherwise a product's flow could be sitting in a
directory we failed to join, and `unavailable` would be a false negative.

So this source closes its own world: if any directory fails to join, products without one
get `unknown`; once every directory resolves, they get a provable `unavailable`.

This is the only data-source fact derivable today. The richer one — which events feed a
product — depends on `setupProbe` in manifest.tsx, which exactly one product declares.
"""

from __future__ import annotations

from ..context import DerivationContext
from ..models import SurfaceFact

_ONBOARDING_RELDIR = "docs/onboarding"

# Shared plumbing, not SDKs.
_NON_SDK_STEMS = frozenset({"index", "steps", "library-docs", "package", "tsconfig"})


def _scan(ctx: DerivationContext) -> tuple[dict[str, tuple[str, list[str]]], list[str]]:
    """Returns (product -> (relpath, sdks), unjoined directory names)."""
    onboarding_root = ctx.repo_root / _ONBOARDING_RELDIR
    by_product: dict[str, tuple[str, list[str]]] = {}
    unjoined: list[str] = []

    if not onboarding_root.is_dir():
        return by_product, unjoined

    # Directories are kebab-case (`ai-observability`) while product dirs are snake_case,
    # hence the join rather than a direct lookup.
    for entry in sorted(onboarding_root.iterdir()):
        if not entry.is_dir():
            continue
        join = ctx.join(entry.name)
        if join.product is None:
            unjoined.append(entry.name)
            continue
        sdks = sorted({f.stem for f in entry.iterdir() if f.suffix in {".tsx", ".ts"} and f.stem not in _NON_SDK_STEMS})
        by_product[join.product] = (f"{_ONBOARDING_RELDIR}/{entry.name}/", sdks)

    return by_product, unjoined


def unattributed_dirs(ctx: DerivationContext) -> list[str]:
    return sorted(_scan(ctx)[1])


def derive(ctx: DerivationContext) -> dict[str, SurfaceFact]:
    by_product, unjoined = _scan(ctx)
    world_is_open = bool(unjoined)

    results: dict[str, SurfaceFact] = {}
    for product in sorted(ctx.product_dirs):
        found = by_product.get(product)

        if found is None:
            if world_is_open:
                results[product] = SurfaceFact(
                    availability="unknown",
                    unknown_reason=(
                        f"onboarding attribution is incomplete — {len(unjoined)} directory(ies) under "
                        f"{_ONBOARDING_RELDIR}/ name no product, so absence of a flow is not provable"
                    ),
                )
            else:
                results[product] = SurfaceFact(
                    availability="unavailable",
                    facts={"count": 0},
                    **{"from": [f"{_ONBOARDING_RELDIR}/"]},
                )
            continue

        rel, sdks = found
        results[product] = SurfaceFact(
            availability="available" if sdks else "unavailable",
            facts={"sdks": sdks, "count": len(sdks)},
            **{"from": [rel]},
        )
    return results
