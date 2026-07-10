#!/usr/bin/env python3
"""Per-product backend coverage reporter.

Reads the coverage.xml files produced by the turbo-tests product matrix (one per
product, written into each product's working dir by `--cov=backend`), computes a
line-coverage percentage per touched product, and renders an ASCII-bar summary.

Only touched products run in CI, so whatever coverage.xml files are present *are*
the touched set — no need to be told which products changed.

Split products write partial coverage.xml across several shards; this unions the
covered line numbers per source file across all shards for a product, so the
percentage is exact rather than a per-shard average.

When GITHUB_TOKEN + PR number are present the report is posted as a sticky PR
comment (find-or-update by marker). Otherwise it's printed to stdout.

stdlib only — mirrors scripts/test_analyze.py.
"""

from __future__ import annotations

import os
import sys
import json
import argparse
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


def collect(artifacts_dir: Path) -> list[ProductCoverage]:
    """Walk artifacts for products/<name>/coverage.xml and roll up per product."""
    # product -> filename -> set of line numbers
    covered: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    valid: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))

    for xml_path in sorted(artifacts_dir.rglob("*.xml")):
        product = product_from_path(xml_path)
        if not product:
            continue
        parse_xml(xml_path, covered[product], valid[product])

    results: list[ProductCoverage] = []
    for product in sorted(valid):
        total_valid = sum(len(lines) for lines in valid[product].values())
        total_covered = sum(len(lines) for lines in covered[product].values())
        results.append(ProductCoverage(product=product, covered=total_covered, valid=total_valid))
    return results


def bar(pct: float) -> str:
    filled = round(pct / 100 * BAR_WIDTH)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def render_markdown(results: list[ProductCoverage]) -> str:
    lines = [
        MARKER,
        "### 🧪 Backend test coverage — touched products",
        "",
    ]
    if not results:
        lines.append("_No product backends were touched by this PR._")
        return "\n".join(lines)

    lines += [
        "| Product | Coverage | Lines |",
        "| --- | --- | --- |",
    ]
    for r in sorted(results, key=lambda x: x.pct):
        lines.append(f"| `{r.product}` | `{bar(r.pct)}` {r.pct:.1f}% | {r.covered:,} / {r.valid:,} |")

    lines += [
        "",
        "_Report-only. Line coverage of `products/<name>/backend` measured during this PR's "
        "product test run (low-overhead `sysmon` backend). Sorted lowest first._",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True, type=Path, help="dir holding downloaded coverage-xml-* artifacts")
    parser.add_argument("--out", type=Path, help="also write the markdown to this path")
    args = parser.parse_args()

    results = collect(args.artifacts)
    markdown = render_markdown(results)

    if args.out:
        args.out.write_text(markdown)
    sys.stdout.write(markdown + "\n")

    if not results:
        # Nothing touched a product backend — don't create comment noise.
        sys.stderr.write("No product coverage found — skipping comment post\n")
        return 0

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")
    if token and repo and pr_number:
        try:
            post_comment(repo, int(pr_number), token, markdown)
        except urllib.error.HTTPError as exc:
            sys.stderr.write(
                f"::warning::failed to post coverage comment: {exc} {exc.read().decode(errors='replace')}\n"
            )
    else:
        sys.stderr.write("No GITHUB_TOKEN/PR context — skipping comment post\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
