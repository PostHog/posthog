"""Audit the Python test suite: count, growth, cost, and consolidation candidates.

Answers three questions with repo-local data:

1. How many tests are there, and how fast is the suite growing?
   (per-test services bill the *expanded* count, parameterization included)
2. Where does the time go? (``.test_durations`` per-test timings used by pytest-split)
3. Which tests look like agent-generated near-duplicates worth merging into
   one parameterized test? (AST shape hashing across test bodies)

    hogli test:audit                # inventory + durations + duplicates + growth
    hogli test:audit --collect      # also run `pytest --collect-only` (~3 min) for the
                                    # exact expanded count and the no-timing-data join
    hogli test:audit -o audit.md    # write the markdown report to a file

What this does not do: judge value. A slow test can be worth every second and a
fast one can be dead weight. Pair the cost tables here with failure history
(Trunk flaky tests / the trunkio_* warehouse tables) before deleting anything,
and apply the writing-tests gate: what realistic regression does this test
catch that no existing test catches?
"""

from __future__ import annotations

import re
import ast
import sys
import json
import hashlib
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import click

# A test recorded at exactly this many seconds smells like a recording cap,
# not a true runtime — flag the cluster instead of trusting the number.
CAP_SECONDS = 60.0
# Bodies smaller than this hash to the same trivial shapes; ignore them.
MIN_BODY_STATEMENTS = 4
# Only clusters at least this large are worth a human's attention.
MIN_CLUSTER_SIZE = 3

NODEID_RE = re.compile(r"^[\w./-]+\.py::")
DEF_TEST_RE = re.compile(rb"^\s*(async )?def test_")


@dataclass(frozen=True, kw_only=True)
class _GrowthRow:
    month: str
    defs: int
    files: int


@dataclass(frozen=True, kw_only=True)
class _DupeCluster:
    members: list[str]  # nodeids
    seconds: float


def _root() -> Path:
    return Path(_sh("git", "rev-parse", "--show-toplevel"))


def _sh(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        raise click.ClickException(f"{' '.join(args)} failed: {result.stderr.strip()[:300]}")
    return result.stdout.strip()


def _test_files(root: Path) -> list[str]:
    out = _sh("git", "ls-files", "*.py", cwd=root).splitlines()
    return [f for f in out if f.split("/")[-1].startswith("test_") or f.endswith("_test.py")]


def _count_defs(root: Path) -> int:
    total = 0
    for f in _test_files(root):
        try:
            data = (root / f).read_bytes()
        except OSError:
            continue
        total += sum(1 for line in data.splitlines() if DEF_TEST_RE.match(line))
    return total


def _growth_rows(root: Path, top: int) -> list[_GrowthRow]:
    """(month, def count, file count) sampled at the first commit of each month."""
    months = _sh("git", "log", "--reverse", "--format=%ad", "--date=format:%Y-%m", cwd=root).splitlines()
    months = sorted(set(months))
    rows = []
    for month in months:
        sha = _sh("git", "rev-list", "-1", "--first-parent", f"--before={month}-01T00:00:00", "HEAD", cwd=root)
        if not sha:
            continue
        grep = subprocess.run(
            ["git", "grep", "-E", r"^\s*(async )?def test_", sha, "--", "*.py"],
            capture_output=True,
            text=True,
            cwd=root,
        )
        defs = grep.stdout.count("\n")
        files = sum(
            1
            for f in _sh("git", "ls-tree", "-r", "--name-only", sha, cwd=root).splitlines()
            if f.endswith(".py") and (f.split("/")[-1].startswith("test_") or f.endswith("_test.py"))
        )
        rows.append(_GrowthRow(month=month, defs=defs, files=files))
    return rows[-top:]


def _load_durations(root: Path) -> dict[str, float]:
    path = root / ".test_durations"
    if not path.exists():
        click.echo("warning: no .test_durations; skipping timing sections", err=True)
        return {}
    return json.loads(path.read_text())


def _collect_nodeids() -> set[str] | None:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        timeout=1200,
    )
    nodeids = {line.strip() for line in proc.stdout.splitlines() if NODEID_RE.match(line.strip())}
    if not nodeids:
        click.echo(f"warning: collection produced no tests:\n{proc.stdout[-500:]}\n{proc.stderr[-500:]}", err=True)
        return None
    return nodeids


class _Blank(ast.NodeVisitor):
    """Erase identifiers and literal values so copy-pasted tests hash alike."""

    def visit_Name(self, node: ast.Name) -> None:
        node.id = "_"

    def visit_arg(self, node: ast.arg) -> None:
        node.arg = "_"

    def visit_Constant(self, node: ast.Constant) -> None:
        node.value = None


def _body_hash(func: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, int]:
    _Blank().visit(func)
    func.name = "_"
    statements = len(func.body)
    for child in ast.walk(func):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child is not func:
            statements += len(child.body)
    return hashlib.sha256(ast.dump(func).encode()).hexdigest(), statements


def _dupes(root: Path, durations: dict[str, float]) -> list[_DupeCluster]:
    """Cluster tests by normalized body hash."""
    clusters: dict[str, list[str]] = defaultdict(list)

    def visit(node: ast.AST, path: str, qualname: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name  # _body_hash blanks it in place
                if name.startswith("test_"):
                    h, size = _body_hash(child)
                    if size >= MIN_BODY_STATEMENTS:
                        nodeid = f"{path}::{qualname}::{name}" if qualname else f"{path}::{name}"
                        clusters[h].append(nodeid)
                visit(child, path, f"{qualname}::{name}" if qualname else name)
            elif isinstance(child, ast.ClassDef):
                visit(child, path, f"{qualname}::{child.name}" if qualname else child.name)

    for f in _test_files(root):
        try:
            tree = ast.parse((root / f).read_bytes())
        except (SyntaxError, ValueError, OSError):
            continue
        visit(tree, f, "")

    out = []
    for members in clusters.values():
        if len(members) < MIN_CLUSTER_SIZE:
            continue
        seconds = sum(durations.get(nodeid, 0.0) for nodeid in members)
        out.append(_DupeCluster(members=members, seconds=seconds))
    out.sort(key=lambda cluster: (-cluster.seconds, -len(cluster.members)))
    return out


def _pct(part: float, whole: float) -> str:
    return f"{part / whole:.0%}" if whole else "-"


@click.command(name="test:audit", help=__doc__)
@click.option("--collect", "do_collect", is_flag=True, help="Run pytest --collect-only (~3 min) for exact counts.")
@click.option("--top", default=15, show_default=True, help="Rows per table.")
@click.option("--dupes/--no-dupes", default=True, help="Scan for duplicate test bodies.")
@click.option("--growth/--no-growth", default=True, help="Sample def counts across git history.")
@click.option(
    "-o", "--output", type=click.Path(path_type=Path), default=None, help="Write markdown here instead of stdout."
)
def test_audit(do_collect: bool, top: int, dupes: bool, growth: bool, output: Path | None) -> None:
    root = _root()
    lines: list[str] = ["# Python test suite audit", ""]

    files = _test_files(root)
    defs = _count_defs(root)
    lines += [
        "## Inventory",
        "",
        f"- Test files: **{len(files):,}**",
        f"- Test functions (`def test_`): **{defs:,}**",
    ]

    nodeids = _collect_nodeids() if do_collect else None
    if nodeids is not None:
        param = sum(1 for n in nodeids if "[" in n)
        lines += [
            f"- Expanded tests (what a per-test service bills): **{len(nodeids):,}**",
            f"- Parameterized expansions: **{param:,}** ({_pct(param, len(nodeids))} of expanded)",
            "",
            "Run without `--collect` and this section only counts `def test_` lines.",
        ]
    else:
        lines += ["", "Expanded count unknown (run with `--collect`, ~3 min)."]
    lines.append("")

    if growth:
        rows = _growth_rows(root, top=12)
        if len(rows) >= 2:
            first, last = rows[0], rows[-1]
            lines += [
                "## Growth",
                "",
                "| Month | Test functions | Test files |",
                "| --- | ---: | ---: |",
                *[f"| {row.month} | {row.defs:,} | {row.files:,} |" for row in rows],
                "",
                f"Net change {first.month} to {last.month}: **+{last.defs - first.defs:,} functions**.",
                "",
            ]
        else:
            lines += ["## Growth", "", "Not enough git history (shallow clone?). Fetch history to enable.", ""]

    durations = _load_durations(root)
    if durations:
        live = {k: v for k, v in durations.items() if (root / k.split("::")[0]).exists()}
        stale = {k: v for k, v in durations.items() if k not in live}
        total = sum(live.values())
        values = sorted(live.values())
        n = len(values)
        lines += [
            "## Where the time goes",
            "",
            f"- Timed tests with files still in the tree: **{len(live):,}** holding **{total / 3600:.2f} h serial**.",
            f"- Stale entries (file moved or deleted): {len(stale):,} holding {sum(stale.values()) / 3600:.2f} h — ignored below.",
            f"- Median test: **{values[n // 2] * 1000:.0f} ms**. p90: {values[int(n * 0.9)]:.2f} s. p99: {values[int(n * 0.99)]:.2f} s.",
        ]
        sorted_vals = sorted(live.values(), reverse=True)
        for pct in (1, 5, 10):
            k = max(1, n * pct // 100)
            lines.append(f"- Top {pct}% of tests ({k:,}) hold **{_pct(sum(sorted_vals[:k]), total)} of all time**.")
        slow = {k: v for k, v in live.items() if v > 1}
        very_slow = {k: v for k, v in live.items() if v > 10}
        lines += [
            f"- Slower than 1 s: {len(slow):,} tests ({_pct(len(slow), n)}) hold {_pct(sum(slow.values()), total)}.",
            f"- Slower than 10 s: {len(very_slow):,} tests hold {_pct(sum(very_slow.values()), total)}.",
            "",
        ]

        capped = sorted(((k, v) for k, v in live.items() if v == CAP_SECONDS), key=lambda kv: kv[0])
        if capped:
            lines += [
                f"### Recorded at exactly {CAP_SECONDS:.0f} s ({len(capped)} tests)",
                "",
                "A round number this precise looks like a recording cap, not a true runtime. "
                "These probably hung or timed out while timing was recorded — investigate each before trusting anything nearby.",
                "",
                "```",
                *(k for k, _ in capped[:top]),
                "```",
                "",
            ]

        by_file: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
        for k, v in live.items():
            entry = by_file[k.split("::")[0]]
            entry[0] += 1
            entry[1] += v
        lines += [
            f"### Heaviest files (top {top})",
            "",
            "| Seconds | Tests | File |",
            "| ---: | ---: | --- |",
            *(f"| {s:,.0f} | {c:,} | `{f}` |" for f, (c, s) in sorted(by_file.items(), key=lambda kv: -kv[1][1])[:top]),
            "",
        ]

        param_time = sum(v for k, v in live.items() if "[" in k)
        param_n = sum(1 for k in live if "[" in k)
        lines += [
            "### Parameterized share of timed tests",
            "",
            f"{param_n:,} expansions ({_pct(param_n, n)} of timed tests) holding {_pct(param_time, total)} of time.",
            "",
        ]

        if nodeids is not None:
            untimed = nodeids - durations.keys()
            by_seg: dict[str, int] = defaultdict(int)
            for k in untimed:
                by_seg["/".join(k.split("/")[:2])] += 1
            lines += [
                "## Tests with no recorded duration",
                "",
                f"**{len(untimed):,}** of {len(nodeids):,} collected tests have no timing record. "
                "pytest-split assigns them a default weight, so shards carrying many of these are balanced on guesses. "
                "Segments with the most untimed tests:",
                "",
                "| Count | Path |",
                "| ---: | --- |",
                *(f"| {c:,} | `{seg}` |" for seg, c in sorted(by_seg.items(), key=lambda kv: -kv[1])[:top]),
                "",
            ]

    if dupes:
        lines += ["## Duplicate-shape tests", ""]
        clusters = _dupes(root, durations)
        in_clusters = sum(len(c.members) for c in clusters)
        est = sum(c.seconds for c in clusters)
        lines += [
            f"Tests in clusters of {MIN_CLUSTER_SIZE}+ with identical bodies (modulo names and literals): "
            f"**{in_clusters:,}** in **{len(clusters):,}** clusters"
            + (f", ~{est / 60:.0f} min of recorded time." if est else "."),
            "",
            "Each cluster is one parameterized test waiting to happen. Check the surviving test covers every case, "
            "then delete the copies — deletion still needs a human to name what coverage is lost.",
            "",
            "| Cluster size | Est. seconds | Example |",
            "| ---: | ---: | --- |",
        ]
        for cluster in clusters[:top]:
            lines.append(f"| {len(cluster.members)} | {cluster.seconds:,.1f} | `{cluster.members[0]}` |")
        lines.append("")

    report = "\n".join(lines)
    if output:
        output.write_text(report + "\n")
        click.echo(f"wrote {output}")
    else:
        click.echo(report)
