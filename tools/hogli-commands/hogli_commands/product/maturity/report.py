"""Render the maturity grid, single-product detail, and codegen report."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

from ..isolation import IsolationStatus
from ..paths import PRODUCTS_DIR
from ..ts_helpers import codegen_call_sites
from . import scores


@dataclass(frozen=True)
class IsolatedTestsState:
    # state: "ON" | "READY" | "OFF". reason: the remaining blocker or live status.
    state: str
    reason: str


_DIM_ORDER = ["models", "facade", "presentation", "boundaries", "codegen"]

_DIM_SHORT = {
    "models": "models",
    "facade": "facade",
    "presentation": "presnt",
    "boundaries": "bounds",
    "codegen": "codgen",
}

_BAR_WIDTH = 15

_MINI_WIDTH = 6


def _bar(score: int, width: int = _BAR_WIDTH) -> str:
    filled = round(score * width / 100)
    return "\u2588" * filled + "\u2591" * (width - filled)


def _mini_bar(dim: scores.DimensionScore) -> str:
    """5-char mini bar for heatmap grid. N/A dims show dots."""
    if not dim.applicable:
        return "\u00b7" * _MINI_WIDTH
    filled = round(dim.score * _MINI_WIDTH / 100)
    return "\u2588" * filled + "\u2591" * (_MINI_WIDTH - filled)


def _dim_line(dim: scores.DimensionScore, connector: str = "\u251c\u2500") -> str:
    if not dim.applicable:
        return f"  {connector} {dim.name:14s}    -  ({dim.detail})"
    return f"  {connector} {dim.name:14s}  {dim.score:3d}  {_bar(dim.score)}  {dim.detail}"


def _isolated_tests_state(status: IsolationStatus) -> IsolatedTestsState:
    """State and reason for the isolated-tests certificate \u2014 the contract-check skip."""
    if status.isolated_tests_enabled:
        return IsolatedTestsState("ON", "contract-check skip live \u2014 Django suite stays off unrelated CI shards")
    # Eligibility deliberately excludes the tach interface (see IsolationStatus), but the skip
    # is unsound without the external boundary, so READY also requires it.
    if status.eligible_for_isolated_tests and status.externally_sealed:
        missing = []
        if not status.has_contract_check_script:
            missing.append("add backend:contract-check")
        if not status.has_narrowed_turbo:
            missing.append("narrow turbo.json inputs")
        return IsolatedTestsState("READY", f"{' + '.join(missing)} to turn the skip on")
    blockers: list[str] = []
    if not status.is_isolated:
        blockers.append("add a facade (contracts.py + api.py)")
    elif not status.has_real_facade:
        blockers.append("make facade/api.py real (define functions, not re-exports)")
    if status.has_legacy_leaks:
        blockers.append("remove the legacy interface leak block from tach.toml")
    if status.deferred_count > 0:
        blockers.append(f"empty the {status.deferred_count} presentation bypass(es)")
    if not status.has_tach_interface:
        blockers.append("add the tach [[interfaces]] block")
    return IsolatedTestsState("OFF", "; ".join(blockers) if blockers else "prerequisites incomplete")


def _isolation_capstone(status: IsolationStatus) -> list[str]:
    """Render the external-vs-internal seal synthesis: the headline an agent acts on.

    Maps the two seals onto the isolated-tests certificate. The boundary protects
    external consumers (tach); the seal stops the product's own presentation bypassing
    its facade (import-linter). Both done + a real facade earns the contract-check skip.
    """
    if status.externally_sealed:
        ext_state, ext_detail = "sealed", "tach [[interfaces]] on, no legacy leaks"
    elif not status.has_tach_interface:
        ext_state, ext_detail = "open", "no tach [[interfaces]] block \u2014 external code can reach internals"
    else:
        ext_state, ext_detail = "open", "legacy interface leak block present \u2014 core still imports internals"

    if not status.is_isolated:
        int_state, int_detail = "n/a", "no facade yet \u2014 product not isolated"
    elif status.internally_sealed:
        int_state, int_detail = "sealed", "presentation reaches internals only through the facade"
    else:
        int_state, int_detail = (
            f"{status.deferred_count} open",
            "presentation still reaches internals directly (see presentation dimension)",
        )

    tests = _isolated_tests_state(status)

    rows = [
        ("external boundary", ext_state, ext_detail),
        ("internal seal", int_state, int_detail),
        ("isolated tests", tests.state, tests.reason),
    ]
    lines = ["  isolation seal"]
    for label, state, detail in rows:
        lines.append(f"    {label:18s}  {state:10s}  {detail}")
    return lines


SEAL_LEGEND = "seal: on=tests live  ready=eligible, not wired  int:N=N internal bypasses open  ext\u2717=external boundary open  \u2014=not isolated"


def _seal_token(status: IsolationStatus | None) -> str:
    """Compact seal state for the --all grid. Each token names the remaining blocker."""
    if status is None or not status.is_isolated:
        return "\u2014"
    if status.isolated_tests_enabled:
        return "on"
    if not status.externally_sealed:
        return "ext\u2717"
    if status.deferred_count > 0:
        # externally sealed but internally unsealed \u2014 looks done, isn't
        return f"int:{status.deferred_count}"
    if status.eligible_for_isolated_tests:
        return "ready"
    return "partial"


def generate_report(scores: list[scores.ProductScore]) -> str:
    """Generate a heatmap grid report for all products."""
    lines: list[str] = []

    lines.append("Product Maturity Report")
    lines.append("")
    lines.append("Dimensions (sequential): models \u2192 facade \u2192 presentation \u2192 boundaries \u2192 codegen")
    lines.append("")

    # Summary
    applicable = [s for s in scores if s.overall is not None]
    if applicable:
        overall_scores = [s.overall for s in applicable if s.overall is not None]
        avg = round(sum(overall_scores) / len(overall_scores))
        high = sum(1 for s in applicable if (s.overall or 0) >= 80)
        mid = sum(1 for s in applicable if 50 <= (s.overall or 0) < 80)
        low = sum(1 for s in applicable if (s.overall or 0) < 50)
        lines.append(f"{len(applicable)} products, avg {avg}/100  ({high} high, {mid} mid, {low} low)")
        lines.append("")

    # Find max product name length for alignment
    scored = [ps for ps in scores if ps.overall is not None]
    max_name = max((len(ps.product) for ps in scored), default=20)
    name_w = max(max_name, 20)

    # Header
    lines.append(SEAL_LEGEND)
    lines.append("")
    dim_header = "  ".join(f"{_DIM_SHORT[d]:>{_MINI_WIDTH}s}" for d in _DIM_ORDER)
    lines.append(f"{'':>{name_w}s}  score  {dim_header}  seal")
    lines.append("")

    # Rows
    for ps in scored:
        dim_map = ps.dimension_map
        mini_bars = "  ".join(_mini_bar(dim_map[d]) if d in dim_map else "\u00b7" * _MINI_WIDTH for d in _DIM_ORDER)
        lines.append(f"{ps.product:>{name_w}s}  {ps.overall:>3d}    {mini_bars}  {_seal_token(ps.isolation)}")

    # Owner rollup
    owner_scores: dict[str, list[int]] = {}
    for ps in scores:
        if ps.overall is not None:
            for owner in ps.owners:
                owner_scores.setdefault(owner, []).append(ps.overall)

    if owner_scores:
        lines.append("")
        lines.append("By Team")
        for owner, vals in sorted(owner_scores.items(), key=lambda t: -sum(t[1]) / len(t[1])):
            avg = round(sum(vals) / len(vals))
            lines.append(f"  {owner:40s}  {avg:3d}  {_bar(avg, 10)}  ({len(vals)} products)")
        lines.append("")

    return "\n".join(lines)


def generate_detail(ps: scores.ProductScore) -> str:
    """Generate detailed single-product maturity breakdown with tree connectors.

    Each dimension that scored below 100 is followed by a "to fix" block listing
    concrete agent-actionable steps, an "evidence" section with structured
    findings (call sites, violations, etc.), and the skills to invoke.
    """
    lines: list[str] = []

    overall = ps.overall
    score_str = "N/A" if overall is None else f"{overall}/100"
    name = ps.display_name or ps.product
    owner_str = f" ({', '.join(ps.owners)})" if ps.owners else ""
    lines.append(f"{name}{owner_str}  {score_str}")
    lines.append("")

    if ps.isolation is not None:
        lines.extend(_isolation_capstone(ps.isolation))
        lines.append("")

    applicable = list(ps.dimensions)
    target_line_width = 100
    for i, dim in enumerate(applicable):
        is_last = i == len(applicable) - 1
        connector = "\u2514\u2500" if is_last else "\u251c\u2500"
        lines.append(_dim_line(dim, connector))

        has_body = bool(dim.next_steps or dim.skills or dim.evidence)
        if not has_body:
            if not is_last:
                lines.append(f"  \u2502")
            continue

        # Indent guide matches the tree above. Use a vertical bar for non-last
        # dimensions so the tree stays visually intact, spaces for the last.
        guide = "\u2502" if not is_last else " "
        gutter = f"  {guide}     "  # column under "\u251c\u2500 <name>"
        bullet_indent = f"{gutter}  "
        cont_indent = f"{gutter}    "
        # Wrap so the rendered line (gutter + bullet + text) stays under target.
        wrap_width = max(40, target_line_width - len(cont_indent))

        blank = f"  {guide}"
        sections_emitted = 0

        # Blank line under the score, then the body
        lines.append(blank)

        if dim.next_steps:
            lines.append(f"{gutter}to fix:")
            for j, step in enumerate(dim.next_steps):
                wrapped = textwrap.wrap(step, width=wrap_width) or [step]
                lines.append(f"{bullet_indent}\u2022 {wrapped[0]}")
                for cont in wrapped[1:]:
                    lines.append(f"{cont_indent}{cont}")
                if j < len(dim.next_steps) - 1:
                    lines.append(blank)
            sections_emitted += 1

        for label, items in dim.evidence:
            if not items:
                continue
            if sections_emitted:
                lines.append(blank)
            lines.append(f"{gutter}{label}:")
            for item in items:
                lines.append(f"{bullet_indent}{item}")
            sections_emitted += 1

        if dim.skills:
            if sections_emitted:
                lines.append(blank)
            skills_str = "  ".join(dim.skills)
            lines.append(f"{gutter}skills: {skills_str}")

        if not is_last:
            lines.append(blank)

    if overall is not None:
        lines.append("")
        lines.append(f"  {'overall':>17s}  {overall:3d}  {_bar(overall)}")

    return "\n".join(lines)


def generate_codegen_report(products: list[str] | None = None) -> str:
    """Generate a detailed codegen adoption report showing call sites and matches.

    If products is None, reports on all products with manual API calls.
    """

    if products is None:
        products = sorted(
            d.name
            for d in PRODUCTS_DIR.iterdir()
            if d.is_dir()
            and not d.name.startswith((".", "_"))
            and d.name != "__pycache__"
            and (d / "__init__.py").exists()
        )

    lines: list[str] = []
    total_manual = 0
    total_matched = 0

    for name in products:
        frontend_dir = PRODUCTS_DIR / name / "frontend"
        if not frontend_dir.exists():
            continue

        sites = codegen_call_sites(frontend_dir)
        if not sites:
            continue

        matched = sum(1 for s in sites if s.generated_equivalent)
        total_manual += len(sites)
        total_matched += matched

        pct = round(100 * matched / len(sites)) if sites else 0
        lines.append(f"{name}  {matched}/{len(sites)} matched ({pct}%)")

        for site in sites:
            arrow = f"→ {site.generated_equivalent}" if site.generated_equivalent else "  (no match)"
            lines.append(f"  {site.file}:{site.line}  {site.verb}({site.url[:50]})  {arrow}")

        lines.append("")

    if total_manual > 0:
        overall_pct = round(100 * total_matched / total_manual)
        header = f"Codegen adoption: {total_matched}/{total_manual} manual calls have generated equivalents ({overall_pct}%)\n"
    else:
        header = "No manual API calls found.\n"

    return header + "\n" + "\n".join(lines)
