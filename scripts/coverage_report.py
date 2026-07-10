#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["diff-cover>=9,<11"]
# ///
"""Per-product backend coverage reporter.

Reads the coverage.xml files produced by the turbo-tests product matrix (one per
product, written into each product's working dir by `--cov=backend`), computes a
line-coverage percentage per touched product, and renders a bar-chart summary.

Only touched products run in CI, so whatever coverage.xml files are present *are*
the touched set — no need to be told which products changed.

Split products write partial coverage.xml across several shards; this unions the
covered line numbers per source file across all shards for a product, so the
percentage is exact rather than a per-shard average.

When GITHUB_TOKEN + PR number are present and the PR leaves product-backend lines
uncovered, the report is posted as a sticky PR comment (find-or-update by marker);
a PR with no uncovered changed lines clears any stale comment. Otherwise it prints
to stdout.

stdlib only — mirrors scripts/test_analyze.py.
"""

from __future__ import annotations

import os
import re
import sys
import json
import argparse
import tempfile
import subprocess
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

MARKER = "<!-- posthog-backend-coverage -->"
BAR_WIDTH = 20


def sanitize_path(path: str) -> str:
    """Keep artifact-derived paths inert in markdown/HTML-comment contexts."""
    return re.sub(r"[^A-Za-z0-9_./\- ]", "_", path).replace("--", "-")


@dataclass
class ProductCoverage:
    product: str
    covered: int
    valid: int

    @property
    def pct(self) -> float:
        return 100.0 * self.covered / self.valid if self.valid else 0.0


def product_from_path(xml_path: Path) -> str | None:
    """Derive the product name from a coverage XML path.

    CI stages each file as <product>.xml (the product survives upload-artifact's
    path collapse). Fall back to the .../products/<name>/coverage.xml layout for
    files read straight from a checkout.
    """
    if xml_path.stem != "coverage":
        return xml_path.stem
    parts = xml_path.parts
    if "products" in parts:
        idx = parts.index("products")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def parse_xml(xml_path: Path, covered_lines: dict[str, set[int]], valid_lines: dict[str, set[int]]) -> None:
    """Accumulate covered / valid line numbers per source file from one coverage.xml."""
    try:
        root = ElementTree.parse(xml_path).getroot()
    except ElementTree.ParseError as exc:
        sys.stderr.write(f"::warning::skipping unparseable {xml_path}: {exc}\n")
        return

    for cls in root.iter("class"):
        filename = cls.get("filename")
        if not filename:
            continue
        for line in cls.iter("line"):
            number_attr = line.get("number")
            if number_attr is None:
                continue
            number = int(number_attr)
            valid_lines[filename].add(number)
            if int(line.get("hits", "0")) > 0:
                covered_lines[filename].add(number)


# product -> filename -> set of line numbers
LineMap = dict[str, dict[str, set[int]]]


def aggregate(artifacts_dir: Path) -> tuple[LineMap, LineMap]:
    """Union covered / valid line numbers per product per source file across all shard XMLs."""
    covered: LineMap = defaultdict(lambda: defaultdict(set))
    valid: LineMap = defaultdict(lambda: defaultdict(set))
    for xml_path in sorted(artifacts_dir.rglob("*.xml")):
        product = product_from_path(xml_path)
        if not product:
            continue
        parse_xml(xml_path, covered[product], valid[product])
    return covered, valid


def collect(covered: LineMap, valid: LineMap) -> list[ProductCoverage]:
    """Roll the per-file line sets up to one coverage figure per product."""
    results: list[ProductCoverage] = []
    for product in sorted(valid):
        total_valid = sum(len(lines) for lines in valid[product].values())
        total_covered = sum(len(lines) for lines in covered[product].values())
        results.append(ProductCoverage(product=product, covered=total_covered, valid=total_valid))
    return results


def resolve_core_path(filename: str, sources: list[str], cache: dict[str, str]) -> str:
    """Reconstruct a repo-relative path from a source-stripped core coverage filename.

    Coverage stores core filenames relative to a <source> root (e.g. ``auth.py`` under source
    ``posthog``), not repo-relative — even with relative_files. Pick the source whose joined
    path exists in the checkout; posthog wins ties since it's the bulk of core.
    """
    if filename in cache:
        return cache[filename]
    stripped = filename.lstrip("/")
    resolved = stripped
    if not stripped.startswith(("posthog/", "ee/")):
        for src in sorted(sources, key=lambda s: 0 if s == "posthog" else 1):
            if src and Path(src, stripped).exists():
                resolved = f"{src}/{stripped}"
                break
        else:
            resolved = f"{sources[0]}/{stripped}" if sources else stripped
    cache[filename] = resolved
    return resolved


def aggregate_core(artifacts_dir: Path) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
    """Union covered / valid line numbers per file across the core (posthog/ee) coverage XMLs.

    Filenames are stored relative to their <source> root (posthog or ee); each is resolved
    back to a repo-relative path so diff-cover can match it against git diff paths.
    """
    covered: dict[str, set[int]] = defaultdict(set)
    valid: dict[str, set[int]] = defaultdict(set)
    cache: dict[str, str] = {}
    for xml_path in sorted(artifacts_dir.rglob("*.xml")):
        try:
            root = ElementTree.parse(xml_path).getroot()
        except ElementTree.ParseError as exc:
            sys.stderr.write(f"::warning::skipping unparseable {xml_path}: {exc}\n")
            continue
        sources = [s.text.strip() for s in root.iter("source") if s.text and s.text.strip() not in (".", "")]
        for cls in root.iter("class"):
            filename = cls.get("filename")
            if not filename:
                continue
            repo_path = resolve_core_path(filename, sources, cache)
            for line in cls.iter("line"):
                number_attr = line.get("number")
                if number_attr is None:
                    continue
                number = int(number_attr)
                valid[repo_path].add(number)
                if int(line.get("hits", "0")) > 0:
                    covered[repo_path].add(number)
    return covered, valid


def repo_path_for(product: str, filename: str) -> str:
    """Map a per-product coverage filename to its repo-relative path.

    turbo runs each product's backend:test with ``--cov=backend``, so coverage records
    filenames relative to ``products/<product>/backend`` (e.g. ``api.py``,
    ``migrations/0001.py``) — the ``backend/`` source root is stripped from the stored
    name. diff-cover matches against repo-relative ``git diff`` paths, so restore it.
    """
    filename = filename.lstrip("/")
    if filename == "backend" or filename.startswith("backend/"):
        return f"products/{product}/{filename}"
    return f"products/{product}/backend/{filename}"


def write_combined_cobertura(
    covered: LineMap,
    valid: LineMap,
    core_covered: dict[str, set[int]],
    core_valid: dict[str, set[int]],
    out_path: Path,
) -> None:
    """Emit one repo-relative Cobertura XML (products + core) from the unioned line sets.

    Product files are rewritten via repo_path_for(); core (posthog/ee) files are already
    repo-relative. <source> points at the repo root so diff-cover matches git diff paths.
    """
    coverage_el = ElementTree.Element("coverage", {"version": "diff-cover-combined"})
    ElementTree.SubElement(ElementTree.SubElement(coverage_el, "sources"), "source").text = "."
    classes_el = ElementTree.SubElement(
        ElementTree.SubElement(ElementTree.SubElement(coverage_el, "packages"), "package", {"name": "backend"}),
        "classes",
    )

    def add_class(repo_path: str, covered_lines: set[int], valid_lines: set[int]) -> None:
        class_el = ElementTree.SubElement(classes_el, "class", {"filename": repo_path, "name": Path(repo_path).name})
        lines_el = ElementTree.SubElement(class_el, "lines")
        for number in sorted(valid_lines):
            hit = "1" if number in covered_lines else "0"
            ElementTree.SubElement(lines_el, "line", {"number": str(number), "hits": hit})

    for product in sorted(valid):
        for filename in sorted(valid[product]):
            add_class(repo_path_for(product, filename), covered[product].get(filename, set()), valid[product][filename])
    for filename in sorted(core_valid):
        add_class(filename, core_covered.get(filename, set()), core_valid[filename])

    ElementTree.ElementTree(coverage_el).write(out_path, encoding="utf-8", xml_declaration=True)


def run_diff_cover(combined_path: Path, compare_branch: str, json_out: Path | None) -> dict | None:
    """Shell out to diff-cover and return its parsed JSON report, or None on any failure.

    Best-effort: a missing diff-cover binary, no git history, or an empty diff all just
    mean no patch section — never a hard error in a report-only job. When json_out is set
    the report is also persisted there (CI uploads it as the machine-readable payload).
    """
    with tempfile.TemporaryDirectory() as tmp:
        report = json_out if json_out is not None else Path(tmp) / "patch.json"
        extra = ["--compare-branch", compare_branch, "--format", f"json:{report}"]
        for invocation in (["diff-cover"], [sys.executable, "-m", "diff_cover.diff_cover_tool"]):
            try:
                proc = subprocess.run([*invocation, str(combined_path), *extra], capture_output=True, text=True)
            except FileNotFoundError:
                continue
            if proc.returncode != 0:
                sys.stderr.write(f"::warning::diff-cover exited {proc.returncode}: {proc.stderr.strip()}\n")
                return None
            try:
                return json.loads(Path(report).read_text())
            except (OSError, json.JSONDecodeError) as exc:
                sys.stderr.write(f"::warning::could not read diff-cover JSON: {exc}\n")
                return None
        sys.stderr.write("::warning::diff-cover not installed — skipping patch coverage\n")
        return None


def bar(pct: float) -> str:
    filled = round(pct / 100 * BAR_WIDTH)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def compress_ranges(numbers: list[int]) -> list[tuple[int, int]]:
    """Collapse a line-number list into sorted (start, end) ranges."""
    nums = sorted(set(numbers))
    ranges: list[tuple[int, int]] = []
    if not nums:
        return ranges
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        ranges.append((start, prev))
        start = prev = n
    ranges.append((start, prev))
    return ranges


def format_line_ranges(numbers: list[int]) -> str:
    """Render line numbers as compact ranges, e.g. [408,409,410,412] -> '408–410, 412'."""
    return ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in compress_ranges(numbers))


def render_patch_section(data: dict) -> str:
    """Render the human-facing patch-coverage block from diff-cover's JSON report."""
    total_lines = int(data.get("total_num_lines", 0))
    if not total_lines:
        return "_No measured backend lines changed in this PR (patch coverage n/a)._"

    pct = float(data.get("total_percent_covered", 0))
    violations = int(data.get("total_num_violations", 0))
    covered = total_lines - violations
    header = f"**Patch coverage** — changed backend lines (products + core): `{bar(pct)}` {pct:.1f}% ({covered:,} / {total_lines:,})"
    if not violations:
        return f"{header}\n\nAll changed backend lines are covered ✅"

    src = data.get("src_stats", {})
    rows = ["", "| File | Patch | Uncovered changed lines |", "| --- | --- | --- |"]
    for path in sorted(src, key=lambda p: src[p].get("percent_covered", 0)):
        missing = format_line_ranges(src[path].get("violation_lines", []))
        if not missing:
            continue
        rows.append(f"| `{sanitize_path(path)}` | {float(src[path].get('percent_covered', 0)):.1f}% | {missing} |")
    return header + "\n" + "\n".join(rows)


def build_agent_hint() -> str:
    """Visible steering line pointing agents at the action + the machine-readable payload."""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run_id:
        payload = f"the **patch-coverage** artifact on [this run]({server}/{repo}/actions/runs/{run_id}) (`gh run download {run_id} -n patch-coverage`)"
    else:
        payload = "the **patch-coverage** artifact"
    return (
        '🤖 **Agents:** add a test covering the lines above, or note why under "How did you test '
        f'this code?". Machine-readable gap list: {payload}, or the `coverage-data` block at the end of this comment.'
    )


def delta_label(pct: float, base: float | None) -> str:
    """Human Δ vs the master baseline; 'new' when the product has no baseline yet."""
    if base is None:
        return "new"
    diff = pct - base
    if abs(diff) < 0.05:
        return "±0%"
    return f"{'▲' if diff > 0 else '▼'} {abs(diff):.1f}%"


def render_product_table(results: list[ProductCoverage], baseline: dict[str, float]) -> list[str]:
    """Per-product absolute coverage, with a Δ-vs-master column when a baseline is present."""
    if baseline:
        rows = ["| Product | Coverage | Δ vs master | Lines |", "| --- | --- | --- | --- |"]
        for r in sorted(results, key=lambda x: x.pct):
            rows.append(
                f"| `{r.product}` | `{bar(r.pct)}` {r.pct:.1f}% | {delta_label(r.pct, baseline.get(r.product))} | {r.covered:,} / {r.valid:,} |"
            )
        return rows
    rows = ["| Product | Coverage | Lines |", "| --- | --- | --- |"]
    for r in sorted(results, key=lambda x: x.pct):
        rows.append(f"| `{r.product}` | `{bar(r.pct)}` {r.pct:.1f}% | {r.covered:,} / {r.valid:,} |")
    return rows


def build_machine_block(patch_data: dict, results: list[ProductCoverage], baseline: dict[str, float]) -> str:
    """A hidden, compact JSON block agents can parse straight from the comment body."""
    src = patch_data.get("src_stats", {})
    payload = {
        "patch": {
            "pct": round(float(patch_data.get("total_percent_covered", 0)), 1),
            "changed": int(patch_data.get("total_num_lines", 0)),
            "uncovered": int(patch_data.get("total_num_violations", 0)),
        },
        "uncovered_lines": {
            sanitize_path(path): [[a, b] for a, b in compress_ranges(stats.get("violation_lines", []))]
            for path, stats in src.items()
            if stats.get("violation_lines")
        },
        "products": {
            r.product: {
                "pct": round(r.pct, 1),
                "base": round(baseline[r.product], 1) if r.product in baseline else None,
                "delta": round(r.pct - baseline[r.product], 1) if r.product in baseline else None,
            }
            for r in results
        },
    }
    return f"<!-- coverage-data:{json.dumps(payload, separators=(',', ':'))} -->"


def render_markdown(results: list[ProductCoverage], patch_data: dict | None, baseline: dict[str, float]) -> str:
    lines = [MARKER, "### 🧪 Backend test coverage", ""]
    if not results and patch_data is None:
        lines.append("_No backend coverage measured for this PR._")
        return "\n".join(lines)

    patch_section = (
        render_patch_section(patch_data) if patch_data is not None else "_Patch coverage unavailable for this run._"
    )
    lines += [patch_section, ""]

    if patch_data is not None and int(patch_data.get("total_num_violations", 0)) > 0:
        lines += [build_agent_hint(), ""]

    # Per-product table is products only — core isn't a product, and on selected-mode runs its
    # absolute number would be partial. Core still contributes to the patch section above.
    if results:
        lines += ["<details>", "<summary>Per-product line coverage (touched products)</summary>", ""]
        lines += render_product_table(results, baseline)
        lines += ["", "</details>"]

    delta_note = " Δ is vs the latest master baseline." if baseline else ""
    lines += [
        "",
        f"_Report-only. Patch coverage = changed backend lines covered vs `origin/master`.{delta_note} Sorted lowest first._",
    ]
    if patch_data is not None:
        lines += ["", build_machine_block(patch_data, results, baseline)]
    return "\n".join(lines)


def load_baseline(path: Path | None) -> dict[str, float]:
    """Load {product: coverage_pct} from a master baseline JSON; {} if absent or unreadable."""
    if path is None or not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"::warning::ignoring unreadable baseline {path}: {exc}\n")
        return {}
    pcts: dict[str, float] = {}
    for product, stats in raw.items():
        valid = stats.get("valid", 0)
        pcts[product] = 100.0 * stats.get("covered", 0) / valid if valid else 0.0
    return pcts


def write_baseline(covered: LineMap, valid: LineMap, out_path: Path) -> None:
    """Write a per-product {covered, valid} baseline JSON (master side; PRs read it for Δ)."""
    base = {
        product: {
            "covered": sum(len(s) for s in covered[product].values()),
            "valid": sum(len(s) for s in valid[product].values()),
        }
        for product in valid
    }
    out_path.write_text(json.dumps(base, separators=(",", ":")))


def gh_request(method: str, url: str, token: str, payload: dict | None = None) -> bytes:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def find_sticky_comment(repo: str, pr: int, token: str) -> int | None:
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/issues/{pr}/comments?per_page=100&page={page}"
        comments = json.loads(gh_request("GET", url, token))
        if not comments:
            return None
        for comment in comments:
            if comment.get("user", {}).get("login") != "github-actions[bot]":
                continue
            if MARKER in (comment.get("body") or ""):
                return comment["id"]
        page += 1


def post_comment(repo: str, pr: int, token: str, body: str) -> None:
    existing = find_sticky_comment(repo, pr, token)
    if existing is not None:
        url = f"https://api.github.com/repos/{repo}/issues/comments/{existing}"
        gh_request("PATCH", url, token, {"body": body})
        sys.stdout.write(f"Updated sticky coverage comment {existing}\n")
    else:
        url = f"https://api.github.com/repos/{repo}/issues/{pr}/comments"
        gh_request("POST", url, token, {"body": body})
        sys.stdout.write("Created sticky coverage comment\n")


def delete_sticky_comment(repo: str, pr: int, token: str) -> bool:
    """Delete the sticky coverage comment if present; return whether one was removed."""
    existing = find_sticky_comment(repo, pr, token)
    if existing is None:
        return False
    gh_request("DELETE", f"https://api.github.com/repos/{repo}/issues/comments/{existing}", token)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True, type=Path, help="dir holding downloaded coverage-xml-* artifacts")
    parser.add_argument("--out", type=Path, help="also write the markdown to this path")
    parser.add_argument(
        "--combined-out", type=Path, help="write a repo-relative combined Cobertura XML here (enables patch coverage)"
    )
    parser.add_argument("--compare-branch", default="origin/master", help="diff-cover compare branch")
    parser.add_argument("--patch-json-out", type=Path, help="path for diff-cover's JSON report (machine payload)")
    parser.add_argument("--baseline", type=Path, help="master coverage baseline JSON to compute per-product Δ against")
    parser.add_argument("--write-baseline", type=Path, help="master side: write the per-product baseline JSON and exit")
    parser.add_argument(
        "--core-artifacts", type=Path, help="dir of core (posthog/ee) coverage-core-* artifacts to include"
    )
    args = parser.parse_args()

    covered, valid = aggregate(args.artifacts)

    if args.write_baseline is not None:
        write_baseline(covered, valid, args.write_baseline)
        sys.stderr.write(f"Wrote coverage baseline for {len(valid)} products to {args.write_baseline}\n")
        return 0

    core_covered: dict[str, set[int]] = {}
    core_valid: dict[str, set[int]] = {}
    if args.core_artifacts is not None and args.core_artifacts.exists():
        core_covered, core_valid = aggregate_core(args.core_artifacts)

    results = collect(covered, valid)  # per-product table is products only; core feeds patch coverage
    baseline = load_baseline(args.baseline)

    patch_data: dict | None = None
    if args.combined_out is not None and (results or core_valid):
        write_combined_cobertura(covered, valid, core_covered, core_valid, args.combined_out)
        patch_data = run_diff_cover(args.combined_out, args.compare_branch, args.patch_json_out)

    markdown = render_markdown(results, patch_data, baseline)

    if args.out:
        args.out.write_text(markdown)
    sys.stdout.write(markdown + "\n")

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")
    if not (token and repo and pr_number):
        sys.stderr.write("No GITHUB_TOKEN/PR context — skipping comment post\n")
        return 0

    # Comment only when this PR leaves product-backend lines uncovered — the actionable case.
    # No coverable change or full coverage clears any stale comment; an undetermined patch
    # (diff-cover unavailable, or no product ran) leaves whatever is there untouched.
    if patch_data is None:
        sys.stderr.write("Patch coverage undetermined — leaving any existing comment untouched\n")
        return 0
    uncovered = int(patch_data.get("total_num_violations", 0))
    try:
        if uncovered > 0:
            post_comment(repo, int(pr_number), token, markdown)
        else:
            removed = delete_sticky_comment(repo, int(pr_number), token)
            state = "removed stale comment" if removed else "nothing to post"
            sys.stderr.write(f"No uncovered changed product-backend lines — {state}\n")
    except urllib.error.HTTPError as exc:
        sys.stderr.write(f"::warning::coverage comment update failed: {exc} {exc.read().decode(errors='replace')}\n")
    except urllib.error.URLError as exc:
        sys.stderr.write(f"::warning::coverage comment update failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
