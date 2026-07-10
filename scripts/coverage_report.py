#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["diff-cover>=9,<11"]
# ///
"""Per-product backend coverage reporter.

Reads the coverage.xml files produced by the turbo-tests product matrix (one per
product, written into each product's working dir by `--cov=backend`), computes a
line-coverage percentage per touched product, and renders an ASCII-bar summary.

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


def write_combined_cobertura(covered: LineMap, valid: LineMap, out_path: Path) -> None:
    """Emit one repo-relative Cobertura XML from the unioned line sets, for diff-cover.

    Each product's coverage.xml stores filenames relative to the product dir (the turbo
    CWD), e.g. ``backend/api.py``. diff-cover matches coverage filenames against ``git
    diff`` paths, which are repo-relative, so prefix ``products/<name>/`` and point
    <source> at the repo root.
    """
    coverage_el = ElementTree.Element("coverage", {"version": "diff-cover-combined"})
    sources_el = ElementTree.SubElement(coverage_el, "sources")
    ElementTree.SubElement(sources_el, "source").text = "."
    classes_el = ElementTree.SubElement(
        ElementTree.SubElement(ElementTree.SubElement(coverage_el, "packages"), "package", {"name": "products"}),
        "classes",
    )

    for product in sorted(valid):
        for filename in sorted(valid[product]):
            class_el = ElementTree.SubElement(
                classes_el, "class", {"filename": f"products/{product}/{filename}", "name": Path(filename).name}
            )
            lines_el = ElementTree.SubElement(class_el, "lines")
            hit = covered[product].get(filename, set())
            for number in sorted(valid[product][filename]):
                ElementTree.SubElement(lines_el, "line", {"number": str(number), "hits": "1" if number in hit else "0"})

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


def format_line_ranges(numbers: list[int]) -> str:
    """Compress a line-number list into compact ranges, e.g. [408,409,410,412] -> '408–410, 412'."""
    nums = sorted(set(numbers))
    if not nums:
        return ""
    ranges: list[tuple[int, int]] = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        ranges.append((start, prev))
        start = prev = n
    ranges.append((start, prev))
    return ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in ranges)


def render_patch_section(data: dict) -> str:
    """Render the human-facing patch-coverage block from diff-cover's JSON report."""
    total_lines = int(data.get("total_num_lines", 0))
    if not total_lines:
        return "_No measured product-backend lines changed in this PR (patch coverage n/a)._"

    pct = float(data.get("total_percent_covered", 0))
    violations = int(data.get("total_num_violations", 0))
    covered = total_lines - violations
    header = f"**Patch coverage** — changed lines in product backends: `{bar(pct)}` {pct:.1f}% ({covered:,} / {total_lines:,})"
    if not violations:
        return f"{header}\n\nAll changed product-backend lines are covered ✅"

    src = data.get("src_stats", {})
    rows = ["", "| File | Patch | Uncovered changed lines |", "| --- | --- | --- |"]
    for path in sorted(src, key=lambda p: src[p].get("percent_covered", 0)):
        missing = format_line_ranges(src[path].get("violation_lines", []))
        if not missing:
            continue
        rows.append(f"| `{path}` | {float(src[path].get('percent_covered', 0)):.1f}% | {missing} |")
    return header + "\n" + "\n".join(rows)


def render_markdown(results: list[ProductCoverage], patch_section: str | None) -> str:
    lines = [MARKER, "### 🧪 Backend test coverage", ""]
    if not results:
        lines.append("_No product backends were touched by this PR._")
        return "\n".join(lines)

    lines += [patch_section or "_Patch coverage unavailable for this run._", ""]

    lines += [
        "<details>",
        "<summary>Per-product line coverage (touched products)</summary>",
        "",
        "| Product | Coverage | Lines |",
        "| --- | --- | --- |",
    ]
    for r in sorted(results, key=lambda x: x.pct):
        lines.append(f"| `{r.product}` | `{bar(r.pct)}` {r.pct:.1f}% | {r.covered:,} / {r.valid:,} |")

    lines += [
        "",
        "</details>",
        "",
        "_Report-only. Patch coverage compares changed lines against `origin/master`; per-product "
        "figures cover `products/<name>/backend` measured during this PR's test run. Sorted lowest first._",
    ]
    return "\n".join(lines)


def gh_request(method: str, url: str, token: str, payload: dict | None = None) -> bytes:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def find_sticky_comment(repo: str, pr: int, token: str) -> int | None:
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/issues/{pr}/comments?per_page=100&page={page}"
        comments = json.loads(gh_request("GET", url, token))
        if not comments:
            return None
        for comment in comments:
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
    args = parser.parse_args()

    covered, valid = aggregate(args.artifacts)
    results = collect(covered, valid)

    patch_data: dict | None = None
    patch_section: str | None = None
    if args.combined_out is not None and results:
        write_combined_cobertura(covered, valid, args.combined_out)
        patch_data = run_diff_cover(args.combined_out, args.compare_branch, args.patch_json_out)
        if patch_data is not None:
            patch_section = render_patch_section(patch_data)

    markdown = render_markdown(results, patch_section)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
