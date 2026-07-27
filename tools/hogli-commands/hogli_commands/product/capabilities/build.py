"""Build the derived product capability spec.

Orchestrates the per-surface derivation sources, enforces the invariants that keep the
output honest, and serializes the result.

Surfaces not yet derived emit `unknown` with a reason rather than being omitted — a
consumer must be able to tell "we know this is false" from "we haven't computed it".
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import click

from ..paths import PRODUCTS_DIR, REPO_ROOT
from .context import DerivationContext
from .join import assert_no_ambiguous_joins
from .models import PROSE_KEYS, CapabilitySpec, ProductCapability, SurfaceFact, UnattributedFacts, unknown
from .sources import mcp, onboarding, platform, scouts

SPEC_VERSION = "0.1.0"

DEFAULT_OUTPUT = REPO_ROOT / "dist" / "product-capabilities.json"

# Surfaces with no derivation yet. Each names the specific thing that would close it, so
# the gap is actionable rather than just an absence.
DEFERRED_SURFACES: dict[str, str] = {
    "web": "not yet derived — requires productManifestFacts.json from frontend/build-products.mjs",
    "max_ai": "not yet derived — requires AST over products/*/backend/max_tools.py",
    "api": "not yet derived — requires OpenAPI x-product attribution",
    "slack": "not yet derived — requires AST over posthog/urls.py slack routes",
    "alerts": "not yet derived — requires import-graph analysis of products.alerts.backend",
    "cli": "cli/ carries no product attribution",
}

DEFERRED_DATA_SOURCES: dict[str, str] = {
    "events": "requires setupProbe in manifest.tsx, which only one product declares today",
    "max_context": "not yet derived — requires scanning ee/hogai/context/",
}

SURFACE_KEYS = ["web", "mcp", "max_ai", "self_driving", "api", "slack", "alerts", "cli"]
DATA_SOURCE_KEYS = ["onboarding_sdks", "events", "max_context"]


def _product_dirs() -> set[str]:
    """Products in the same sense `hogli product:lint` uses: a directory with __init__.py."""
    return {d.name for d in PRODUCTS_DIR.iterdir() if d.is_dir() and (d / "__init__.py").exists()}


def _assert_complete(source_name: str, facts: dict[str, SurfaceFact], product_dirs: set[str]) -> None:
    """A source must answer for every product. Silence is not a verdict."""
    missing = product_dirs - facts.keys()
    extra = facts.keys() - product_dirs
    if missing or extra:
        raise ValueError(
            f"source `{source_name}` returned an incomplete product set — "
            f"missing={sorted(missing)} unexpected={sorted(extra)}"
        )


def _assert_no_prose(payload: str) -> None:
    """The artifact states facts; posthog.com writes the words."""
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in PROSE_KEYS:
                    found.add(key)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(json.loads(payload))
    if found:
        raise ValueError(f"capability spec contains prose keys {sorted(found)} — it must carry facts only")


def build_spec(*, release: bool = False) -> CapabilitySpec:
    product_dirs = _product_dirs()
    ctx = DerivationContext(repo_root=REPO_ROOT, products_dir=PRODUCTS_DIR, product_dirs=product_dirs)

    derived_surfaces = {"mcp": mcp.derive(ctx), "self_driving": scouts.derive(ctx)}
    derived_data_sources = {"onboarding_sdks": onboarding.derive(ctx)}

    for name, facts in {**derived_surfaces, **derived_data_sources}.items():
        _assert_complete(name, facts, product_dirs)

    orphan_scopes = scouts.unattributed_scopes(ctx)
    assert_no_ambiguous_joins(sorted(product_dirs) + orphan_scopes, product_dirs, ctx.aliases)

    from ..product_yaml import load_product_yaml

    products: list[ProductCapability] = []
    for name in sorted(product_dirs):
        meta = load_product_yaml(name)
        products.append(
            ProductCapability(
                product=name,
                name=meta.get("name") or name,
                owners=list(meta.get("owners") or []),
                surfaces={
                    key: derived_surfaces[key][name] if key in derived_surfaces else unknown(DEFERRED_SURFACES[key])
                    for key in SURFACE_KEYS
                },
                data_sources={
                    key: derived_data_sources[key][name]
                    if key in derived_data_sources
                    else unknown(DEFERRED_DATA_SOURCES[key])
                    for key in DATA_SOURCE_KEYS
                },
            )
        )

    spec = CapabilitySpec(
        spec_version=SPEC_VERSION,
        products=products,
        platform=platform.derive(ctx),
        unattributed=UnattributedFacts(scout_scopes=orphan_scopes),
    )

    if release:
        spec.generated_at = datetime.now(UTC).isoformat()
        spec.commit_sha = _current_commit()

    return spec


def _current_commit() -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def serialize(spec: CapabilitySpec) -> str:
    payload = spec.model_dump_json(by_alias=True, indent=4, exclude_none=False)
    _assert_no_prose(payload)
    return payload + "\n"


def _summarize(spec: CapabilitySpec) -> str:
    counts: dict[str, dict[str, int]] = {}
    for product in spec.products:
        for key, fact in {**product.surfaces, **product.data_sources}.items():
            counts.setdefault(key, {}).setdefault(fact.availability, 0)
            counts[key][fact.availability] += 1

    lines = [f"{len(spec.products)} products", ""]
    for key in SURFACE_KEYS + DATA_SOURCE_KEYS:
        breakdown = ", ".join(f"{v} {k}" for k, v in sorted(counts.get(key, {}).items()))
        lines.append(f"  {key:18} {breakdown}")
    if spec.unattributed.scout_scopes:
        lines += [
            "",
            f"  unattributed scout scopes ({len(spec.unattributed.scout_scopes)}): "
            + ", ".join(spec.unattributed.scout_scopes),
        ]
    return "\n".join(lines)


@click.command(name="build:product-capabilities")
@click.option("--release", is_flag=True, help="Stamp generated_at + commit_sha and write to dist/.")
@click.option("--product", "product_name", default=None, help="Dump a single product to stdout, write nothing.")
@click.option("--output", type=click.Path(path_type=Path), default=None, help="Override the output path.")
def cmd_build(release: bool, product_name: str | None, output: Path | None) -> None:
    """Derive the product capability spec from the repo."""
    spec = build_spec(release=release)

    if product_name:
        match = next((p for p in spec.products if p.product == product_name), None)
        if match is None:
            raise click.ClickException(f"unknown product `{product_name}`")
        click.echo(match.model_dump_json(by_alias=True, indent=4))
        return

    destination = output or DEFAULT_OUTPUT
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(serialize(spec))
    click.echo(_summarize(spec))
    click.echo(f"\nwrote {destination.relative_to(REPO_ROOT)}")


@click.command(name="lint:product-capabilities")
def cmd_lint() -> None:
    """Validate every capability derivation source without writing anything."""
    try:
        spec = build_spec()
        serialize(spec)
    except Exception as exc:
        raise click.ClickException(f"capability spec derivation failed: {exc}") from exc
    click.echo(_summarize(spec))
    click.echo("\ncapability sources OK")
