"""Dimension 4: tach interfaces and cross-product import hygiene."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..isolation import has_legacy_interface_leaks, has_tach_interface
from ..paths import REPO_ROOT, TACH_TOML, get_tach_block
from . import common, scores


@dataclass(frozen=True)
class CrossImportMaps:
    # inbound[target]: external code importing a product's non-facade internals.
    # outbound[source]: a product importing another product's non-facade internals.
    # Each value is a list of `relpath:line  module` evidence strings.
    inbound: dict[str, list[str]]
    outbound: dict[str, list[str]]


def _count_tach_depends_on(block: str) -> tuple[int, list[str]]:
    """Count non-baseline depends_on entries in a tach block.

    Baseline dependencies (posthog, ee) are expected and don't count.
    Cross-product dependencies are the coupling signal.
    """
    baseline = {"posthog", "ee"}
    deps: list[str] = []
    in_depends = False
    for line in block.split("\n"):
        stripped = line.strip()
        if stripped.startswith("depends_on"):
            if "[" in stripped and "]" in stripped:
                for dep in re.findall(r'"([^"]+)"', stripped):
                    if dep not in baseline:
                        deps.append(dep)
                break
            in_depends = True
            continue
        if in_depends:
            if stripped == "]":
                break
            dep = stripped.strip('"').strip(",").strip('"')
            if dep and dep not in baseline:
                deps.append(dep)
    return len(deps), deps


def _build_cross_import_maps() -> CrossImportMaps | None:
    """One rg pass over the repo, distributed into the inbound and outbound maps.

    Both maps read the same `import products.<x>.backend.<…>` lines, so they share a single
    scan instead of re-walking every product's files per product. Returns None if rg is
    unavailable or times out.
    """
    try:
        result = subprocess.run(
            ["rg", "-n", "--type", "py", r"(?:from|import)\s+products\.\w+\.backend\.", str(REPO_ROOT)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    inbound: dict[str, list[str]] = {}
    outbound: dict[str, list[str]] = {}
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        # rg -n format: <path>:<line>:<text>
        colon_idx = line.find(":", 1)
        if colon_idx == -1:
            continue
        colon2_idx = line.find(":", colon_idx + 1)
        if colon2_idx == -1:
            continue
        file_path = line[:colon_idx]
        line_num = line[colon_idx + 1 : colon2_idx]
        import_text = line[colon2_idx + 1 :].strip()

        # Which product is being imported? (handles both from/import style)
        match = re.search(r"products\.(\w+)\.backend\.\w+", import_text)
        if not match:
            continue
        imported = match.group(1)
        module = match.group(0)

        try:
            rel_path = str(Path(file_path).relative_to(REPO_ROOT))
        except ValueError:
            rel_path = file_path
        evidence = f"{rel_path}:{line_num}  {module}"

        # Which product owns the importing file? Empty when it lives in core (ee/, posthog/).
        src = re.match(r"products/(\w+)/", rel_path)
        source = src.group(1) if src else ""

        is_facade = ".backend.facade" in import_text
        is_presentation = ".backend.presentation" in import_text

        # inbound: someone outside `imported` reaching past its facade/presentation surface.
        # Django admin's project-wide registry must import each product's admin classes and
        # the models they reference — there's no facade equivalent for `admin.site.register`.
        in_admin = "/posthog/admin/" in file_path or rel_path.startswith("posthog/admin/")
        if (
            source != imported
            and not is_facade
            and not is_presentation
            and "/migrations/" not in file_path
            and not in_admin
        ):
            inbound.setdefault(imported, []).append(evidence)

        # outbound: `source` reaching into another product's non-facade internals.
        if source and source != imported and not is_facade:
            outbound.setdefault(source, []).append(evidence)

    return CrossImportMaps(inbound, outbound)


def score_boundaries(
    name: str,
    product_dir: Path,
    inbound_map: dict[str, list[str]] | None = None,
    outbound_map: dict[str, list[str]] | None = None,
    tach_content: str | None = None,
) -> scores.DimensionScore:
    """Tach interfaces + cross-product import hygiene.

    Points breakdown (100 total):
      tach.toml entry + interfaces:               10
      no cross-product depends_on in tach:         15 (coupling declaration)
      no outbound non-facade imports:              15 (this product's own code)
      no inbound non-facade imports:               60 (the big one — others
        bypassing the facade is the real isolation failure)
    """
    if not common._has_python_files(product_dir):
        return scores.DimensionScore("boundaries", 0, "no Python files", applicable=False)

    content = tach_content if tach_content is not None else (TACH_TOML.read_text() if TACH_TOML.exists() else "")

    score = 0
    parts = []
    next_steps: list[str] = []
    evidence: list[tuple[str, list[str]]] = []

    # Tach entry + interfaces
    module_path = f"products.{name}"
    block = get_tach_block(module_path)

    if block:
        if has_tach_interface(name, content):
            score += 10
            parts.append("tach + interfaces")
        else:
            score += 5
            parts.append("tach (no interfaces)")
            next_steps.append(
                f'Add `interfaces = ["products.{name}.backend.facade.*", '
                f'"products.{name}.backend.presentation.*"]` to the [[modules]] entry in '
                f"tach.toml so tach enforces what's public."
            )

        # Cross-product depends_on: each one is an explicit coupling
        n_cross_deps, cross_deps = _count_tach_depends_on(block)
        if n_cross_deps == 0:
            score += 15
            parts.append("no cross-product deps")
        else:
            score += max(0, 15 - n_cross_deps * 5)
            parts.append(f"{n_cross_deps} cross-product deps")
            next_steps.append(
                f"Drop the {n_cross_deps} cross-product depends_on entry/entries from tach.toml "
                f"(listed below). If a real dependency exists, route through that product's "
                f"facade so the coupling is interface-level rather than module-level."
            )
            evidence.append(("tach depends_on", list(cross_deps)))
    else:
        parts.append("not in tach.toml")
        next_steps.append(
            f"Add a [[modules]] entry for products.{name} to tach.toml with explicit "
            f"`depends_on` and `interfaces`. Without it, tach won't catch boundary regressions."
        )

    # Outbound: this product importing other products' internals
    outbound = outbound_map.get(name, []) if outbound_map is not None else None
    if outbound is None:
        parts.append("outbound scan failed")
        next_steps.append(
            "Outbound scan failed — `rg` is missing or timed out. Install ripgrep and re-run "
            "`hogli product:maturity` for an accurate outbound count."
        )
    elif not outbound:
        score += 15
        parts.append("outbound clean")
    else:
        score += max(0, 15 - len(outbound) * 5)
        parts.append(f"{len(outbound)} outbound violations")
        next_steps.append(
            f"Replace the {len(outbound)} outbound import(s) of other products' internals listed "
            f"below with calls to those products' facades."
        )
        evidence.append(("outbound violations", common._cap(outbound, 25)))

    # Inbound: other code importing this product's non-facade internals
    inbound = inbound_map.get(name, []) if inbound_map is not None else None
    if inbound is None:
        parts.append("inbound scan failed")
        next_steps.append(
            "Inbound scan failed — `rg` is missing or timed out. Install ripgrep and re-run "
            "`hogli product:maturity` for an accurate inbound count."
        )
    elif not inbound:
        score += 60
        parts.append("inbound clean")
    else:
        score += max(0, 60 - len(inbound) * 3)
        parts.append(f"{len(inbound)} inbound violations")
        next_steps.append(
            f"Audit the {len(inbound)} external import(s) of this product's internals listed "
            f"below. Each one either belongs in the facade's public surface (then expose it "
            f"through facade.api) or should not exist (refactor the caller). Update tach "
            f"`interfaces` to match."
        )
        # Cap evidence so the report doesn't explode for products with hundreds of violations
        evidence.append(("inbound violations", common._cap(inbound, 25)))

    # A declared legacy-leak interface (e.g. backend.admin exposed to core) is an external
    # bypass the inbound scan deliberately exempts. Without docking it here, a leaky product
    # still scores a near-perfect boundary while the seal capstone says the boundary is open.
    if has_legacy_interface_leaks(content, module_path):
        score -= min(score, 30)
        parts.append("legacy interface leak")
        next_steps.append(
            "A dedicated legacy-leak [[interfaces]] block exposes non-facade internals to core "
            "(e.g. backend.admin). The external boundary stays open until that coupling is removed "
            "or accepted as permanent; contract-check stays off either way."
        )
        evidence.append(("legacy interface leak", [f"{module_path}: non-facade surface exposed to core in tach.toml"]))

    skills = ["/isolating-product-facade-contracts"] if next_steps else []
    return scores.DimensionScore(
        "boundaries", score, ", ".join(parts), next_steps=next_steps, skills=skills, evidence=evidence
    )
