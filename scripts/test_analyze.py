"""Analyze pytest test suite: per-test duration + status, segmented into archetypes.

Inputs (any combination):
  - .test_durations  (pytest-split JSON, repo root) — canonical per-test durations
  - junit XMLs       (CI artifacts) — adds per-shard wall time, setup overhead,
                     status mix, and parametrization data

Output: markdown or self-contained HTML (no external deps).

Usage:
    uv run python scripts/test_analyze.py
    uv run python scripts/test_analyze.py --junit-dir /tmp/testanalyze/run-<id>
    uv run python scripts/test_analyze.py --out logs/test_analysis.md
    uv run python scripts/test_analyze.py --junit-dir <dir> --out logs/test_analysis.html

Once CI starts uploading .testmondata, add a --testmon-db PATH flag and join
per-test file dependencies to surface "covered but slow" and "redundant" archetypes.
"""

from __future__ import annotations

import sys
import html
import json
import math
import sqlite3
import argparse
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DURATIONS_PATH = REPO_ROOT / ".test_durations"
HIGH_FANOUT_PATH = REPO_ROOT / "tools" / "testmon_high_fanout_files.txt"

# Tests touching more files than this are treated as tracing artifacts
# (first-test-in-shard Django bootstrap loads ~1700 production files). Capping
# stops them from inflating the inv-frequency score across the entire suite.
OVERBROAD_FILE_THRESHOLD = 500

# pytest-split's .test_durations writes flat defaults (60.0, 18.0) for tests it
# couldn't time properly — newly added tests, flaky reruns where the timer was
# reset, or removed-but-not-pruned entries. These are NOT timeout kills; on
# successful master runs pytest-timeout would have failed the build. Treat them
# as untrustworthy timing.
SUSPECT_DURATIONS = {60.0, 18.0}
SUSPECT_TOLERANCE = 1e-6


# ---- data model -------------------------------------------------------------


@dataclass
class TestRecord:
    nodeid: str
    duration: float
    status: str = "unknown"  # pass | fail | skip | error | unknown
    files_touched: int = 0  # production files this test exercised (after high-fanout discount)
    files_touched_uncapped: int = 0  # raw count before the over-broad cap
    inv_freq: float = 0.0  # Σ 1/(num_tests_touching_file) — higher = covers rarer files
    min_others: int = 0  # smallest "other tests touching this file" count across this test's files
    rare_files: int = 0  # how many of this test's files are touched by ≤3 other tests
    has_coverage: bool = False  # did testmon record any file deps for this test
    coverage_files: frozenset[str] = field(default_factory=frozenset)  # full file set (after high-fanout discount)

    @property
    def is_overbroad(self) -> bool:
        return self.files_touched_uncapped > OVERBROAD_FILE_THRESHOLD

    @property
    def has_suspect_duration(self) -> bool:
        return any(abs(self.duration - v) < SUSPECT_TOLERANCE for v in SUSPECT_DURATIONS)

    @property
    def top_dir(self) -> str:
        return self.nodeid.split("/", 1)[0] if "/" in self.nodeid else ""

    @property
    def module(self) -> str:
        path, _, _ = self.nodeid.partition("::")
        return path

    @property
    def package(self) -> str:
        parts = self.module.split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else parts[0]

    @property
    def class_id(self) -> str:
        """`file.py::Class` or just `file.py` for top-level tests."""
        parts = self.nodeid.split("::")
        return "::".join(parts[:2]) if len(parts) >= 2 else parts[0]

    @property
    def cluster(self) -> str:
        """Coarse "natural cluster" — a product or top-level feature area.

        - `products/<name>/...` -> `products/<name>`
        - `posthog/<area>/<sub>/...` -> `posthog/<area>/<sub>` (e.g. posthog/hogql_queries/insights)
        - `ee/<area>/...` -> `ee/<area>`
        Falls back to the top-level segment for short paths.
        """
        path = self.nodeid.split("::", 1)[0]
        parts = path.split("/")
        if not parts:
            return path
        if parts[0] == "products" and len(parts) >= 2:
            return f"products/{parts[1]}"
        if parts[0] in {"posthog", "ee"} and len(parts) >= 3:
            return "/".join(parts[:3])
        return parts[0] if parts else path

    @property
    def base_name(self) -> str:
        """Strip parametrization brackets: `test_foo[a-1]` -> `test_foo`."""
        nodeid = self.nodeid
        bracket = nodeid.find("[")
        return nodeid[:bracket] if bracket != -1 else nodeid


@dataclass
class ShardRecord:
    """Per-shard wall-time stats from one junit testsuite."""

    name: str
    suite_time: float
    testcase_sum: float
    test_count: int
    pass_count: int = 0
    fail_count: int = 0
    skip_count: int = 0
    error_count: int = 0
    hostname: str = ""

    @property
    def overhead(self) -> float:
        return max(0.0, self.suite_time - self.testcase_sum)

    @property
    def overhead_pct(self) -> float:
        return 100 * self.overhead / self.suite_time if self.suite_time else 0


# ---- loading ----------------------------------------------------------------


def load_durations(path: Path) -> dict[str, float]:
    if not path.exists():
        sys.exit(f"missing {path} — run pytest with --store-durations on master first")
    return json.loads(path.read_text())


def parse_junit_dir(junit_dir: Path) -> tuple[dict[str, str], list[ShardRecord]]:
    """Return (status-by-nodeid, list of per-shard records)."""
    if not junit_dir.exists():
        return {}, []
    status_by_nodeid: dict[str, str] = {}
    shards: list[ShardRecord] = []
    for xml_path in sorted(junit_dir.rglob("*.xml")):
        try:
            tree = ET.parse(xml_path)
        except ET.ParseError:
            continue
        # Use parent dir as the shard label (matches the artifact name).
        shard_label = xml_path.parent.name.replace("junit-results-backend-", "") or xml_path.stem
        for suite in tree.iter("testsuite"):
            tc_sum = 0.0
            passes = fails = skips = errors = 0
            for case in suite.iter("testcase"):
                t = float(case.get("time", 0))
                tc_sum += t
                classname = case.get("classname", "")
                name = case.get("name", "")
                # Build a nodeid candidate that may match .test_durations format.
                # .test_durations uses `path/to/file.py::Class::method`,
                # junit classname is dotted `pkg.mod.Class` — we lose path/dot info,
                # so we store both forms.
                nodeid_dot = f"{classname}::{name}" if classname else name
                if case.find("failure") is not None:
                    status, fails = "fail", fails + 1
                elif case.find("error") is not None:
                    status, errors = "error", errors + 1
                elif case.find("skipped") is not None:
                    status, skips = "skip", skips + 1
                else:
                    status, passes = "pass", passes + 1
                status_by_nodeid[nodeid_dot] = status
            shards.append(
                ShardRecord(
                    name=shard_label,
                    suite_time=float(suite.get("time", 0)),
                    testcase_sum=tc_sum,
                    test_count=int(suite.get("tests", 0)),
                    pass_count=passes,
                    fail_count=fails,
                    skip_count=skips,
                    error_count=errors,
                    hostname=suite.get("hostname", ""),
                )
            )
    return status_by_nodeid, shards


def load_high_fanout(path: Path) -> set[str]:
    """Files that are touched by ~every test (settings, conftest, db routers).

    Listed in `tools/testmon_high_fanout_files.txt`. Discounted from each test's
    coverage set so the "unique coverage" metric isn't dominated by infrastructure.
    """
    if not path.exists():
        return set()
    return {ln.strip() for ln in path.read_text().splitlines() if ln.strip()}


def load_testmon_dir(testmon_dir: Path, high_fanout: set[str]) -> dict[str, set[str]]:
    """Read all `.testmondata` SQLite files under `testmon_dir` and merge into
    a per-test set of source filenames.

    Each shard's `.testmondata` has tables:
      file_fp(id, filename, ...)
      test_execution(id, test_name, duration, failed, forced, environment_id)
      test_execution_file_fp(test_execution_id, fingerprint_id)

    Within a shard, fingerprint_id == file_fp.id. Across shards we union by
    filename. Empty SQLite files (no `file_fp` table) are skipped — they appear
    in shards that collected no tests.
    """
    test_files: dict[str, set[str]] = defaultdict(set)
    if not testmon_dir.exists():
        return {}
    for db_path in sorted(testmon_dir.rglob(".testmondata")):
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            continue
        try:
            tbls = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "file_fp" not in tbls:
                continue
            files_by_id = dict(conn.execute("SELECT id, filename FROM file_fp"))
            tests_by_id = dict(conn.execute("SELECT id, test_name FROM test_execution"))
            for tid, fid in conn.execute("SELECT test_execution_id, fingerprint_id FROM test_execution_file_fp"):
                tn = tests_by_id.get(tid)
                fn = files_by_id.get(fid)
                if tn and fn and fn not in high_fanout:
                    test_files[tn].add(fn)
        finally:
            conn.close()
    return dict(test_files)


def status_for(nodeid: str, junit_status: dict[str, str]) -> str:
    """Best-effort map of .test_durations nodeid -> junit status.

    Mapping is lossy because junit uses dotted classname while .test_durations
    uses path-form. Returns 'unknown' on no match.
    """
    if not junit_status:
        return "unknown"
    if nodeid in junit_status:
        return junit_status[nodeid]
    module_part, sep, rest = nodeid.partition("::")
    if not sep:
        return "unknown"
    dotted_mod = module_part.replace("/", ".").removesuffix(".py")
    return junit_status.get(f"{dotted_mod}::{rest}", "unknown")


def build_records(
    durations: dict[str, float],
    junit_status: dict[str, str],
    test_files: dict[str, set[str]] | None = None,
) -> list[TestRecord]:
    """Construct per-test records, joining duration + status + testmon coverage."""
    records = [TestRecord(nodeid=n, duration=d, status=status_for(n, junit_status)) for n, d in durations.items()]
    if not test_files:
        return records

    # Cap each test's file set to OVERBROAD_FILE_THRESHOLD when computing the
    # cross-test frequency map, so Django bootstrap artifacts (1700+ files in
    # the first test per shard) don't drown the signal for everyone else.
    file_test_count: dict[str, int] = defaultdict(int)
    for fs in test_files.values():
        if len(fs) > OVERBROAD_FILE_THRESHOLD:
            continue
        for f in fs:
            file_test_count[f] += 1

    for r in records:
        fs = test_files.get(r.nodeid)
        if fs is None:
            continue
        r.has_coverage = True
        r.coverage_files = frozenset(fs)
        r.files_touched_uncapped = len(fs)
        r.files_touched = len(fs)
        if r.is_overbroad:
            continue  # over-broad tests don't get a value score
        counts = [file_test_count[f] for f in fs if file_test_count.get(f)]
        if not counts:
            continue
        r.inv_freq = sum(1.0 / c for c in counts)
        r.min_others = min(counts) - 1  # subtract self
        r.rare_files = sum(1 for c in counts if c <= 4)  # ≤4 incl self → ≤3 others
    return records


# ---- segmentation -----------------------------------------------------------


@dataclass
class Segment:
    name: str
    description: str
    members: list[TestRecord] = field(default_factory=list)

    @property
    def total_time(self) -> float:
        return sum(r.duration for r in self.members)

    @property
    def count(self) -> int:
        return len(self.members)


def segment_by_coverage(records: list[TestRecord]) -> list[Segment]:
    """Segment using both duration and testmon-derived coverage value.

    Requires `has_coverage=True` on at least some records; tests without
    coverage data are bucketed into `no-coverage-data` separately.

    The 2×2 split (slow/fast × unique/redundant) uses:
      - slow = duration > p95 of trustworthy durations
      - unique = inv_freq >= median of records with coverage
    """
    trusted = sorted(r.duration for r in records if not r.has_suspect_duration and r.duration > 0 and r.has_coverage)
    if not trusted:
        # No coverage data — caller should fall back to segment_by_duration.
        return []
    # Slow = top 1% by duration (true outliers). Above this is "actually slow."
    slow_threshold = trusted[int(len(trusted) * 0.99)]
    covered = [r for r in records if r.has_coverage and not r.is_overbroad and r.duration > 0]
    invs = sorted(r.inv_freq for r in covered)
    # Median inv_freq splits "covers rarer code" from "covers only common code".
    rarity_threshold = invs[len(invs) // 2] if invs else 0.0

    segments = [
        Segment(
            "slow_dispensable",
            f"⚠ OPTIMIZE OR DROP — duration ≥ {slow_threshold:.1f}s and covers only commonly-tested files",
        ),
        Segment(
            "slow_irreplaceable",
            f"⚠ OPTIMIZE — duration ≥ {slow_threshold:.1f}s but covers rarer code (don't delete)",
        ),
        Segment(
            "fast_valuable",
            "✓ KEEP — fast workhorse covering rarer code",
        ),
        Segment(
            "fast_broad_only",
            "○ LOW PRIORITY — fast but only touches popular files (NOT a delete candidate, just no value to optimize)",
        ),
        Segment(
            "over_broad_tracer",
            f"○ DATA NOISE — >{OVERBROAD_FILE_THRESHOLD} files touched (first-test-in-shard Django bootstrap)",
        ),
        Segment(
            "missing_coverage",
            "△ NO DATA — no testmon record for this test (didn't run in this CI, Products turbo shards, or a deleted-but-not-pruned entry in .test_durations)",
        ),
        Segment(
            "suspect_duration",
            "△ UNTRUSTED TIMING — flat 60.0/18.0 default from pytest-split, not a real measurement",
        ),
    ]
    by_name = {s.name: s for s in segments}

    for r in records:
        if r.has_suspect_duration:
            by_name["suspect_duration"].members.append(r)
        elif not r.has_coverage:
            by_name["missing_coverage"].members.append(r)
        elif r.is_overbroad:
            by_name["over_broad_tracer"].members.append(r)
        else:
            slow = r.duration >= slow_threshold
            rare = r.inv_freq >= rarity_threshold
            if slow and not rare:
                by_name["slow_dispensable"].members.append(r)
            elif slow and rare:
                by_name["slow_irreplaceable"].members.append(r)
            elif rare:
                by_name["fast_valuable"].members.append(r)
            else:
                by_name["fast_broad_only"].members.append(r)
    return segments


def segment_records(records: list[TestRecord]) -> list[Segment]:
    """Initial segmentation using only duration + suspect-duration flag.

    Coarse buckets — meant to surface the most obvious archetypes before
    coverage data is wired in. Each test lands in exactly one segment.
    """
    trusted = sorted(r.duration for r in records if not r.has_suspect_duration and r.duration > 0)
    p95 = trusted[int(len(trusted) * 0.95)]
    p99 = trusted[int(len(trusted) * 0.99)]

    segments = [
        Segment(
            "suspect-duration",
            f"flat default values {sorted(SUSPECT_DURATIONS)} — pytest-split couldn't time these",
        ),
        Segment("slow-outliers", f"> p99 ({p99:.1f}s) — strongest review candidates"),
        Segment("slow-tail", f"p95–p99 ({p95:.2f}s–{p99:.2f}s)"),
        Segment("normal", f"50ms–p95 ({p95:.2f}s)"),
        Segment("fast", "≤ 50ms — near-zero cost"),
    ]
    by_name = {s.name: s for s in segments}

    for r in records:
        if r.has_suspect_duration:
            by_name["suspect-duration"].members.append(r)
        elif r.duration > p99:
            by_name["slow-outliers"].members.append(r)
        elif r.duration > p95:
            by_name["slow-tail"].members.append(r)
        elif r.duration <= 0.050:
            by_name["fast"].members.append(r)
        else:
            by_name["normal"].members.append(r)
    return segments


# ---- redundancy & staleness -------------------------------------------------


@dataclass
class RedundancyCluster:
    """A group of tests with overlapping coverage signatures.

    isomorph: every member's coverage_files is identical (Jaccard = 1.0).
    near-isomorph: pairwise Jaccard >= threshold (default 0.85) but < 1.0.

    Within a cluster, members are sorted by duration ascending — the fastest
    one is the representative; dropping the rest is the suggested action.
    """

    kind: str
    members: list[TestRecord]
    coverage_size: int
    mean_jaccard: float

    @property
    def representative(self) -> TestRecord:
        return self.members[0]

    @property
    def total_duration(self) -> float:
        return sum(m.duration for m in self.members)

    @property
    def droppable_duration(self) -> float:
        return self.total_duration - self.representative.duration


def find_isomorphs(records: list[TestRecord]) -> list[RedundancyCluster]:
    """Group tests by exact coverage signature — clusters >= 2 are full duplicates."""
    by_sig: dict[frozenset[str], list[TestRecord]] = defaultdict(list)
    for r in records:
        if not r.has_coverage or r.is_overbroad or not r.coverage_files:
            continue
        by_sig[r.coverage_files].append(r)
    clusters: list[RedundancyCluster] = []
    for sig, members in by_sig.items():
        if len(members) < 2:
            continue
        members_sorted = sorted(members, key=lambda r: r.duration)
        clusters.append(
            RedundancyCluster(
                kind="isomorph",
                members=members_sorted,
                coverage_size=len(sig),
                mean_jaccard=1.0,
            )
        )
    return sorted(clusters, key=lambda c: c.droppable_duration, reverse=True)


def find_near_isomorphs(
    records: list[TestRecord],
    isomorph_nodeids: set[str],
    threshold: float = 0.85,
    max_pairs: int = 5_000_000,
) -> list[RedundancyCluster]:
    """Union-find clusters with pairwise Jaccard >= threshold (excluding exact iso).

    Pre-filters candidates by coverage-size bucket: Jaccard <= min/max, so tests
    with very different |coverage| can be skipped. O(N^2) in the worst case but
    in practice well under `max_pairs` after bucketing.
    """
    candidates = [
        r
        for r in records
        if r.has_coverage and not r.is_overbroad and r.coverage_files and r.nodeid not in isomorph_nodeids
    ]
    # bucket-key chosen so two tests in the same bucket have size ratio >= threshold.
    log_base = math.log(1.0 / threshold) if threshold < 1.0 else 1.0
    buckets: dict[int, list[TestRecord]] = defaultdict(list)
    for r in candidates:
        n = len(r.coverage_files)
        key = int(math.log(n) / log_base) if n > 1 else 0
        buckets[key].append(r)
        buckets[key + 1].append(r)  # adjacent bucket to handle boundary tests

    parent: dict[str, str] = {r.nodeid: r.nodeid for r in candidates}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    pairs_checked = 0
    seen_pairs: set[tuple[str, str]] = set()
    for bucket_members in buckets.values():
        if pairs_checked > max_pairs:
            break
        for i, r1 in enumerate(bucket_members):
            for r2 in bucket_members[i + 1 :]:
                pair = (r1.nodeid, r2.nodeid) if r1.nodeid < r2.nodeid else (r2.nodeid, r1.nodeid)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                pairs_checked += 1
                if pairs_checked > max_pairs:
                    break
                inter = len(r1.coverage_files & r2.coverage_files)
                if inter == 0:
                    continue
                uniq = len(r1.coverage_files) + len(r2.coverage_files) - inter
                jacc = inter / uniq
                if threshold <= jacc < 1.0:
                    union(r1.nodeid, r2.nodeid)
            if pairs_checked > max_pairs:
                break

    by_root: dict[str, list[TestRecord]] = defaultdict(list)
    for r in candidates:
        by_root[find(r.nodeid)].append(r)

    clusters: list[RedundancyCluster] = []
    for members in by_root.values():
        if len(members) < 2:
            continue
        members_sorted = sorted(members, key=lambda r: r.duration)
        union_cov: set[str] = set()
        for m in members_sorted:
            union_cov |= m.coverage_files
        # mean pairwise Jaccard only for small clusters (cheap), otherwise approximate.
        if len(members_sorted) <= 8:
            jacc_sum = 0.0
            jacc_n = 0
            for i, a in enumerate(members_sorted):
                for b in members_sorted[i + 1 :]:
                    inter = len(a.coverage_files & b.coverage_files)
                    uniq = len(a.coverage_files | b.coverage_files)
                    if uniq:
                        jacc_sum += inter / uniq
                        jacc_n += 1
            mean_j = jacc_sum / jacc_n if jacc_n else 0.0
        else:
            mean_j = threshold  # placeholder; not worth O(k^2) for big clusters
        clusters.append(
            RedundancyCluster(
                kind="near-isomorph",
                members=members_sorted,
                coverage_size=len(union_cov),
                mean_jaccard=mean_j,
            )
        )
    return sorted(clusters, key=lambda c: c.droppable_duration, reverse=True)


def find_quarantined(records: list[TestRecord]) -> list[TestRecord]:
    """Tests with junit status = skip that still cost collection time."""
    return sorted(
        [r for r in records if r.status == "skip" and r.duration > 0],
        key=lambda r: r.duration,
        reverse=True,
    )


def find_trivial_coverage(records: list[TestRecord]) -> list[TestRecord]:
    """Tests touching only test-helper files / their own module — no production code.

    Heuristic: every covered file lives under a tests/ directory, contains `/test_`,
    ends with `/tests.py`, or is the test's own module. These exercise no production
    paths, so deleting them doesn't lose meaningful coverage.
    """
    out: list[TestRecord] = []
    for r in records:
        if not r.has_coverage or r.is_overbroad or not r.coverage_files:
            continue
        own_module = r.module
        non_test_non_self = [
            f
            for f in r.coverage_files
            if f != own_module and not f.endswith("/tests.py") and "/tests/" not in f and "/test_" not in f
        ]
        if not non_test_non_self:
            out.append(r)
    return sorted(out, key=lambda r: r.duration, reverse=True)


@dataclass
class RedundancyAnalysis:
    """All redundancy + staleness findings, plus the savings tally."""

    isomorphs: list[RedundancyCluster]
    near_isomorphs: list[RedundancyCluster]
    quarantined: list[TestRecord]
    trivial: list[TestRecord]

    @property
    def total_drop_savings(self) -> float:
        """Time saved if we delete isomorph extras + quarantined + trivial-coverage tests."""
        iso = sum(c.droppable_duration for c in self.isomorphs)
        quar = sum(r.duration for r in self.quarantined)
        triv = sum(r.duration for r in self.trivial)
        return iso + quar + triv

    @property
    def drop_count(self) -> int:
        iso = sum(len(c.members) - 1 for c in self.isomorphs)
        return iso + len(self.quarantined) + len(self.trivial)

    @property
    def review_savings(self) -> float:
        """Time saved if near-isomorph clusters get consolidated (lower confidence — needs human review)."""
        return sum(c.droppable_duration for c in self.near_isomorphs)


def analyze_redundancy(records: list[TestRecord]) -> RedundancyAnalysis:
    iso = find_isomorphs(records)
    iso_nodeids = {m.nodeid for c in iso for m in c.members}
    near = find_near_isomorphs(records, iso_nodeids)
    return RedundancyAnalysis(
        isomorphs=iso,
        near_isomorphs=near,
        quarantined=find_quarantined(records),
        trivial=find_trivial_coverage(records),
    )


# ---- shared aggregations ----------------------------------------------------


@dataclass
class ClusterStats:
    """Per-cluster (product or feature-area) resource & coverage roll-up."""

    name: str
    test_count: int
    total_time: float
    mean_duration: float
    cov_count: int  # tests with testmon data
    unique_files: int  # cardinality of union of all files touched by cluster's tests
    mean_files: float  # avg files touched (over tests with coverage)
    mean_inv_freq: float  # avg rarity-weighted coverage (lower = more redundant)
    files_per_hour: float  # unique_files / total_time → "value density"


@dataclass
class Aggregations:
    """Cross-cutting summaries used by both markdown and HTML renderers."""

    total_time: float
    median: float
    p95: float
    p99: float
    max_time: float
    pareto_50: int
    pareto_80: int
    by_package: list[tuple[str, float, int, float]]  # name, total, count, median
    by_class: list[tuple[str, float, int]]  # class_id, total, count
    by_base: list[tuple[str, int, float]]  # base nodeid, param count, total time
    by_cluster: list[ClusterStats]
    status_counts: Counter[str]


def compute_aggregations(records: list[TestRecord], test_files: dict[str, set[str]] | None = None) -> Aggregations:
    total = sum(r.duration for r in records)
    durs = sorted(r.duration for r in records)
    n = len(durs) or 1
    median_v = durs[n // 2]
    p95 = durs[int(n * 0.95)] if n > 1 else 0
    p99 = durs[int(n * 0.99)] if n > 1 else 0
    cum = 0.0
    p50_n = p80_n = n
    for i, d in enumerate(sorted(durs, reverse=True), 1):
        cum += d
        if cum >= total * 0.5 and p50_n == n:
            p50_n = i
        if cum >= total * 0.8:
            p80_n = i
            break

    by_pkg_raw: dict[str, list[float]] = defaultdict(list)
    by_cls_raw: dict[str, list[float]] = defaultdict(list)
    by_base_raw: dict[str, list[float]] = defaultdict(list)
    for r in records:
        by_pkg_raw[r.package].append(r.duration)
        by_cls_raw[r.class_id].append(r.duration)
        by_base_raw[r.base_name].append(r.duration)

    def _pkg_row(name: str, durs: list[float]) -> tuple[str, float, int, float]:
        sd = sorted(durs)
        return name, sum(durs), len(durs), sd[len(sd) // 2]

    by_package = sorted(
        (_pkg_row(p, ds) for p, ds in by_pkg_raw.items()),
        key=lambda r: -r[1],
    )[:25]
    by_class = sorted(
        ((c, sum(ds), len(ds)) for c, ds in by_cls_raw.items()),
        key=lambda r: -r[1],
    )[:25]
    by_base = sorted(
        ((b, len(ds), sum(ds)) for b, ds in by_base_raw.items() if len(ds) > 1),
        key=lambda r: (-r[1], -r[2]),
    )[:25]

    by_cluster = _compute_clusters(records, test_files=test_files)

    return Aggregations(
        total_time=total,
        median=median_v,
        p95=p95,
        p99=p99,
        max_time=durs[-1] if durs else 0,
        pareto_50=p50_n,
        pareto_80=p80_n,
        by_package=by_package,
        by_class=by_class,
        by_base=by_base,
        by_cluster=by_cluster,
        status_counts=Counter(r.status for r in records),
    )


def _compute_clusters(records: list[TestRecord], test_files: dict[str, set[str]] | None = None) -> list[ClusterStats]:
    """Aggregate by 'natural cluster' (product or feature area).

    When testmon data is loaded, also folds in the union of files each cluster
    covers — to surface "lots of tests, few unique files" (over-tested) vs
    "few tests, broad coverage" (efficient).
    """
    by_c: dict[str, list[TestRecord]] = defaultdict(list)
    for r in records:
        by_c[r.cluster].append(r)

    # Re-derive the per-test file map from records: we stored counts but not sets.
    # If test_files is passed explicitly use it; otherwise we approximate using
    # files_touched (cardinality only, no union possible).
    out: list[ClusterStats] = []
    for name, rs in by_c.items():
        total_t = sum(r.duration for r in rs)
        cov_rs = [r for r in rs if r.has_coverage and not r.is_overbroad]
        unique_files = 0
        if test_files is not None and cov_rs:
            union: set[str] = set()
            for r in cov_rs:
                fs = test_files.get(r.nodeid)
                if fs is not None and len(fs) <= OVERBROAD_FILE_THRESHOLD:
                    union |= fs
            unique_files = len(union)
        mean_files = (sum(r.files_touched for r in cov_rs) / len(cov_rs)) if cov_rs else 0.0
        mean_inv = (sum(r.inv_freq for r in cov_rs) / len(cov_rs)) if cov_rs else 0.0
        files_per_hour = (unique_files / (total_t / 3600)) if total_t > 0 and unique_files > 0 else 0.0
        out.append(
            ClusterStats(
                name=name,
                test_count=len(rs),
                total_time=total_t,
                mean_duration=total_t / len(rs) if rs else 0,
                cov_count=len(cov_rs),
                unique_files=unique_files,
                mean_files=mean_files,
                mean_inv_freq=mean_inv,
                files_per_hour=files_per_hour,
            )
        )
    return sorted(out, key=lambda c: -c.total_time)


# ---- formatters -------------------------------------------------------------


def _fmt_h(s: float) -> str:
    return f"{s / 3600:.2f}h" if s >= 3600 else f"{s / 60:.1f}m" if s >= 60 else f"{s:.1f}s"


def _fmt_ms(s: float) -> str:
    return f"{s * 1000:.0f}ms" if s < 1 else f"{s:.2f}s"


# ---- markdown report --------------------------------------------------------


def render_markdown(
    records: list[TestRecord],
    segments: list[Segment],
    aggs: Aggregations,
    shards: list[ShardRecord],
    redundancy: RedundancyAnalysis | None = None,
) -> str:
    lines: list[str] = []
    lines.append("# Test suite analysis")
    lines.append("")
    lines.append(f"- Tests: **{len(records):,}**")
    lines.append(f"- Total test-time: **{_fmt_h(aggs.total_time)}** (single-threaded)")
    lines.append(
        f"- Distribution: median {_fmt_ms(aggs.median)} · p95 {aggs.p95:.2f}s · "
        f"p99 {aggs.p99:.2f}s · max {aggs.max_time:.1f}s"
    )
    lines.append(
        f"- Pareto: 50% in **{aggs.pareto_50:,}** tests ({100 * aggs.pareto_50 / len(records):.1f}%); "
        f"80% in **{aggs.pareto_80:,}** ({100 * aggs.pareto_80 / len(records):.1f}%)"
    )
    lines.append("")

    if redundancy is not None and (redundancy.drop_count or redundancy.near_isomorphs):
        lines.append("## Redundancy & staleness — drop candidates")
        lines.append("")
        lines.append(
            f"- **Drop list**: {redundancy.drop_count:,} tests, {_fmt_h(redundancy.total_drop_savings)} "
            f"(isomorphs + quarantined skips + trivial coverage)"
        )
        if redundancy.isomorphs:
            iso_total = sum(c.droppable_duration for c in redundancy.isomorphs)
            lines.append(
                f"- Isomorphs (identical coverage): {len(redundancy.isomorphs)} clusters, {_fmt_h(iso_total)} droppable"
            )
        if redundancy.quarantined:
            quar_total = sum(r.duration for r in redundancy.quarantined)
            lines.append(
                f"- Quarantined (skipped + costs collection): {len(redundancy.quarantined)} tests, {_fmt_h(quar_total)}"
            )
        if redundancy.trivial:
            triv_total = sum(r.duration for r in redundancy.trivial)
            lines.append(
                f"- Trivial coverage (no production files): {len(redundancy.trivial)} tests, {_fmt_h(triv_total)}"
            )
        if redundancy.near_isomorphs:
            lines.append(
                f"- Near-isomorphs (Jaccard ≥ 0.85, review): {len(redundancy.near_isomorphs)} clusters, "
                f"{_fmt_h(redundancy.review_savings)} potential"
            )
        lines.append("")

    if shards:
        wall = sum(s.suite_time for s in shards)
        tc_sum = sum(s.testcase_sum for s in shards)
        overhead = wall - tc_sum
        lines.append("## Setup overhead (junit)")
        lines.append("")
        lines.append(
            f"- Suite wall (all shards): **{_fmt_h(wall)}** · "
            f"Testcase sum: **{_fmt_h(tc_sum)}** · "
            f"**Setup/teardown overhead: {_fmt_h(overhead)} ({100 * overhead / wall:.1f}%)**"
        )
        lines.append("")
        sranked = sorted(shards, key=lambda x: -x.overhead)
        lines.append("### Top 10 shards by setup overhead")
        lines.append("")
        lines.append("| shard | suite | testcase | overhead | overhead % | tests |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for sh in sranked[:10]:
            lines.append(
                f"| {sh.name} | {sh.suite_time:.0f}s | {sh.testcase_sum:.0f}s | "
                f"{sh.overhead:.0f}s | {sh.overhead_pct:.1f}% | {sh.test_count} |"
            )
        lines.append("")

    lines.append("## Duration segments")
    lines.append("")
    lines.append("| segment | count | total time | % of suite | description |")
    lines.append("|---|---:|---:|---:|---|")
    for s in segments:
        pct = 100 * s.total_time / aggs.total_time if aggs.total_time else 0
        lines.append(f"| {s.name} | {s.count:,} | {_fmt_h(s.total_time)} | {pct:.1f}% | {s.description} |")
    lines.append("")

    for s in segments:
        if not s.members:
            continue
        lines.append(f"### {s.name} — top 10 by duration")
        lines.append("")
        for r in sorted(s.members, key=lambda x: -x.duration)[:10]:
            tag = "" if r.status in ("pass", "unknown") else f" `[{r.status}]`"
            lines.append(f"- `{r.duration:6.2f}s` {r.nodeid}{tag}")
        lines.append("")

    lines.append("## Hottest packages")
    lines.append("")
    lines.append("| package | tests | total time | mean | median |")
    lines.append("|---|---:|---:|---:|---:|")
    for name, total, count, med in aggs.by_package[:20]:
        lines.append(f"| {name} | {count:,} | {_fmt_h(total)} | {total / count:.2f}s | {_fmt_ms(med)} |")
    lines.append("")

    lines.append("## Slowest classes (file::Class)")
    lines.append("")
    lines.append("| class | tests | total time | mean |")
    lines.append("|---|---:|---:|---:|")
    for cid, total, count in aggs.by_class[:20]:
        lines.append(f"| `{cid}` | {count} | {_fmt_h(total)} | {total / count:.2f}s |")
    lines.append("")

    if aggs.by_base:
        lines.append("## Parametrization explosion (top base tests by param count)")
        lines.append("")
        lines.append("| base test | param count | total time |")
        lines.append("|---|---:|---:|")
        for base, n, total in aggs.by_base[:20]:
            lines.append(f"| `{base}` | {n} | {_fmt_h(total)} |")
        lines.append("")

    if aggs.status_counts and set(aggs.status_counts) - {"unknown"}:
        lines.append("## Status mix (from junit)")
        lines.append("")
        for st, n in aggs.status_counts.most_common():
            lines.append(f"- {st}: {n:,}")
        lines.append("")

    return "\n".join(lines)


# ---- HTML report ------------------------------------------------------------

CSS = """
:root { --fg:#0f172a; --muted:#64748b; --bg:#f8fafc; --card:#fff; --line:#e2e8f0;
        --accent:#0ea5e9; --warn:#dc2626; --ok:#16a34a;
        --act-drop:#dc2626; --act-opt:#d97706; --act-keep:#16a34a; --act-low:#64748b; --act-data:#7c3aed; }
* { box-sizing: border-box; }
body { font: 14px/1.5 -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif;
       color: var(--fg); background: var(--bg); margin: 0; padding: 24px; }
.container { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 32px 0 12px; padding-bottom: 4px; border-bottom: 1px solid var(--line); }
h3 { font-size: 14px; margin: 16px 0 6px; color: var(--muted); font-weight: 600; }
.subtitle { color: var(--muted); margin: 0 0 24px; font-size: 13px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 16px 0 24px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 14px 16px; }
.card .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
.card .value { font-size: 22px; font-weight: 600; margin-top: 4px; }
.card .sub { color: var(--muted); font-size: 12px; margin-top: 2px; }
.card.warn .value { color: var(--warn); }
table { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line);
        border-radius: 6px; overflow: hidden; font-size: 13px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
th { background: #f1f5f9; font-weight: 600; color: var(--fg); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tr:last-child td { border-bottom: 0; }
code { font: 12px/1.3 'SF Mono', 'Monaco', monospace; background: #f1f5f9; padding: 1px 4px; border-radius: 3px; }
.path { font: 12px/1.3 'SF Mono', 'Monaco', monospace; color: var(--fg); overflow-wrap: anywhere; white-space: normal; max-width: 600px; }
.badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 11px; font-weight: 600; }
.badge.pass { background: #dcfce7; color: var(--ok); }
.badge.fail, .badge.error { background: #fee2e2; color: var(--warn); }
.badge.skip { background: #fef3c7; color: #b45309; }
.badge.suspect { background: #fce7f3; color: #be185d; }
details > summary { cursor: pointer; padding: 6px 0; color: var(--accent); font-size: 13px; }
.bar-row { display: flex; align-items: center; gap: 8px; padding: 2px 0; font-size: 12px; }
.bar-row .label { flex: 0 0 180px; font: 11px/1.3 'SF Mono', monospace; overflow: hidden; text-overflow: ellipsis; }
.bar-row .bar { flex: 1; height: 14px; background: #f1f5f9; border-radius: 2px; position: relative; overflow: hidden; }
.bar-row .bar .testcase { background: var(--accent); height: 100%; position: absolute; left: 0; top: 0; }
.bar-row .bar .overhead { background: #fca5a5; height: 100%; position: absolute; top: 0; }
.bar-row .value { flex: 0 0 110px; text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
.legend { display: flex; gap: 16px; margin: 8px 0 12px; font-size: 12px; color: var(--muted); }
.legend .sw { display: inline-block; width: 12px; height: 12px; border-radius: 2px; vertical-align: middle; margin-right: 4px; }
.legend .sw.testcase { background: var(--accent); }
.legend .sw.overhead { background: #fca5a5; }
.footnote { color: var(--muted); font-size: 12px; margin-top: 8px; }
/* Executive summary banner */
.banner { background: var(--card); border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 6px;
          padding: 16px 20px; margin: 0 0 24px; }
.banner h2 { font-size: 14px; margin: 0 0 8px; padding: 0; border: 0; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
.banner .finding { font-size: 14px; line-height: 1.6; margin: 0 0 6px; }
.banner .finding strong { font-weight: 600; }
.banner .num { font-variant-numeric: tabular-nums; font-weight: 600; }
.banner .num.bad { color: var(--act-drop); }
.banner .num.warn { color: var(--act-opt); }
.banner-drop { border-left-color: var(--act-drop); }
/* Action labels */
.act { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 700;
       text-transform: uppercase; letter-spacing: .04em; }
.act-drop { background: #fef2f2; color: var(--act-drop); border: 1px solid #fecaca; }
.act-opt  { background: #fffbeb; color: var(--act-opt);  border: 1px solid #fed7aa; }
.act-keep { background: #f0fdf4; color: var(--act-keep); border: 1px solid #bbf7d0; }
.act-low  { background: #f8fafc; color: var(--act-low);  border: 1px solid #e2e8f0; }
.act-data { background: #faf5ff; color: var(--act-data); border: 1px solid #e9d5ff; }
/* Segment row coloring */
tr.seg-drop td:first-child { border-left: 3px solid var(--act-drop); }
tr.seg-opt  td:first-child { border-left: 3px solid var(--act-opt); }
tr.seg-keep td:first-child { border-left: 3px solid var(--act-keep); }
tr.seg-low  td:first-child { border-left: 3px solid var(--act-low); }
tr.seg-data td:first-child { border-left: 3px solid var(--act-data); }
/* Methods footer */
.methods { background: #f1f5f9; border-radius: 6px; padding: 16px 20px; margin-top: 32px; font-size: 12px; color: var(--muted); }
.methods h3 { margin: 0 0 8px; color: var(--fg); font-size: 13px; }
.methods dt { font-weight: 600; color: var(--fg); margin-top: 8px; }
.methods dd { margin: 2px 0 0 0; }
"""

# Map segment name -> action label class + display label.
SEGMENT_ACTIONS: dict[str, tuple[str, str]] = {
    "slow_dispensable": ("drop", "OPTIMIZE OR DROP"),
    "slow_irreplaceable": ("opt", "OPTIMIZE"),
    "fast_valuable": ("keep", "KEEP"),
    "fast_broad_only": ("low", "LOW PRIORITY"),
    "over_broad_tracer": ("data", "DATA NOISE"),
    "missing_coverage": ("data", "NO DATA"),
    "suspect_duration": ("data", "UNTRUSTED TIMING"),
}


def _h(s: str | float) -> str:
    return html.escape(str(s))


def _card(label: str, value: str, sub: str = "", warn: bool = False) -> str:
    cls = "card warn" if warn else "card"
    return (
        f'<div class="{cls}"><div class="label">{_h(label)}</div>'
        f'<div class="value">{_h(value)}</div>'
        f'<div class="sub">{_h(sub)}</div></div>'
    )


def _status_badge(status: str) -> str:
    if status in ("pass", "fail", "error", "skip"):
        return f'<span class="badge {status}">{status}</span>'
    return ""


def _shard_bars(shards: list[ShardRecord]) -> str:
    if not shards:
        return ""
    max_time = max(sh.suite_time for sh in shards)
    rows: list[str] = []
    for sh in sorted(shards, key=lambda x: -x.suite_time):
        tc_pct = 100 * sh.testcase_sum / max_time
        ov_left_pct = tc_pct
        ov_pct = 100 * sh.overhead / max_time
        rows.append(
            f'<div class="bar-row">'
            f'<div class="label">{_h(sh.name)}</div>'
            f'<div class="bar">'
            f'<div class="testcase" style="width:{tc_pct:.2f}%"></div>'
            f'<div class="overhead" style="left:{ov_left_pct:.2f}%;width:{ov_pct:.2f}%"></div>'
            f"</div>"
            f'<div class="value">{sh.suite_time:.0f}s · {sh.test_count} tests</div>'
            f"</div>"
        )
    return "\n".join(rows)


def _exec_summary(
    records: list[TestRecord],
    segments: list[Segment],
    shards: list[ShardRecord],
) -> str:
    """3-5 line top-of-page banner with the most actionable findings."""
    findings: list[str] = []
    seg_by_name = {s.name: s for s in segments}
    if shards:
        wall = sum(sh.suite_time for sh in shards)
        tc_sum = sum(sh.testcase_sum for sh in shards)
        overhead = wall - tc_sum
        pct = 100 * overhead / wall if wall else 0
        cls = "bad" if pct > 70 else "warn" if pct > 40 else ""
        findings.append(
            f"<p class='finding'>● <strong>Setup overhead dominates CI</strong>: "
            f"<span class='num {cls}'>{pct:.0f}%</span> of suite wall ({_fmt_h(overhead)} of {_fmt_h(wall)}) "
            f"is fixtures / DB migrations / container boot, not test code. "
            f"Optimizing tests alone caps at the remaining <span class='num'>{_fmt_h(tc_sum)}</span>.</p>"
        )
        slowest = max(shards, key=lambda x: x.suite_time)
        fastest = min(shards, key=lambda x: x.suite_time)
        ratio = slowest.suite_time / fastest.suite_time if fastest.suite_time else 0
        if ratio > 4:
            findings.append(
                f"<p class='finding'>● <strong>Shard imbalance</strong>: slowest shard is "
                f"<span class='num warn'>{ratio:.1f}×</span> the fastest "
                f"(<code>{_h(slowest.name)}</code> {slowest.suite_time:.0f}s vs "
                f"<code>{_h(fastest.name)}</code> {fastest.suite_time:.0f}s). "
                f"CI wall clock is gated by the slowest shard, not the mean.</p>"
            )
    sd = seg_by_name.get("slow_dispensable")
    if sd and sd.members:
        # Group by base test (without [param]) to find over-parametrization clusters
        by_base: dict[str, list[TestRecord]] = defaultdict(list)
        for r in sd.members:
            by_base[r.base_name].append(r)
        top_clusters = sorted(by_base.items(), key=lambda kv: -sum(r.duration for r in kv[1]))[:3]
        cluster_desc = ", ".join(
            f"<code>{_h(b.rsplit('::', 1)[-1])}</code> ({len(rs)} variants, {_fmt_h(sum(r.duration for r in rs))})"
            for b, rs in top_clusters
            if len(rs) > 1
        )
        findings.append(
            f"<p class='finding'>● <strong>Drop/optimize candidates</strong>: "
            f"<span class='num bad'>{sd.count}</span> tests = "
            f"<span class='num'>{_fmt_h(sd.total_time)}</span> are slow AND cover only commonly-tested code."
            + (f" Top parametrization clusters: {cluster_desc}." if cluster_desc else "")
            + "</p>"
        )
    si = seg_by_name.get("slow_irreplaceable")
    if si and si.members:
        findings.append(
            f"<p class='finding'>● <strong>Optimize (don't delete)</strong>: "
            f"<span class='num warn'>{si.count:,}</span> slow tests cover rarer code — "
            f"<span class='num'>{_fmt_h(si.total_time)}</span> of suite time. Faster fixtures or parallelism, not pruning.</p>"
        )
    susp = seg_by_name.get("suspect_duration")
    if susp and susp.count > 0:
        findings.append(
            f"<p class='finding'>● <strong>Untrusted timings</strong>: "
            f"<span class='num'>{susp.count}</span> tests have flat default values in "
            f"<code>.test_durations</code> ({_fmt_h(susp.total_time)} of recorded time). "
            f"These need a clean re-measurement before optimization claims.</p>"
        )
    missing = seg_by_name.get("missing_coverage")
    if missing and missing.count > 0:
        gap_pct = 100 * missing.count / len(records)
        findings.append(
            f"<p class='finding'>● <strong>Coverage data gap</strong>: "
            f"<span class='num'>{missing.count:,}</span> tests ({gap_pct:.0f}% of suite) lack testmon data — "
            f"didn't run in this CI, ran in a turbo shard without upload, or stale <code>.test_durations</code> entries.</p>"
        )
    if not findings:
        return ""
    return "<div class='banner'><h2>Key findings</h2>" + "".join(findings) + "</div>"


def _action_badge(seg_name: str) -> str:
    cls_short, label = SEGMENT_ACTIONS.get(seg_name, ("low", seg_name))
    return f"<span class='act act-{cls_short}'>{label}</span>"


def _action_row_class(seg_name: str) -> str:
    cls_short, _ = SEGMENT_ACTIONS.get(seg_name, ("low", seg_name))
    return f"seg-{cls_short}"


def _redundancy_banner(redundancy: RedundancyAnalysis) -> str:
    """Headline summary of drop savings — shown above the rest of the report."""
    if redundancy.drop_count == 0 and not redundancy.near_isomorphs:
        return ""
    parts = ["<div class='banner banner-drop'><h2>Redundancy &amp; staleness — drop candidates</h2>"]
    drop_h = _fmt_h(redundancy.total_drop_savings)
    parts.append(
        f"<p class='finding'><strong>Drop list</strong> — "
        f"<span class='num warn'>{redundancy.drop_count:,}</span> tests, "
        f"<span class='num warn'>{drop_h}</span> of test-time. "
        "High-confidence: exact-duplicate coverage, skipped-but-still-collected, or coverage of test-helpers only.</p>"
    )
    if redundancy.near_isomorphs:
        cluster_count = len(redundancy.near_isomorphs)
        member_total = sum(len(c.members) for c in redundancy.near_isomorphs)
        parts.append(
            f"<p class='finding'><strong>Review list</strong> — "
            f"<span class='num'>{cluster_count}</span> near-isomorph clusters "
            f"({member_total} tests, {_fmt_h(redundancy.review_savings)} potential) — Jaccard ≥ 0.85, "
            "needs human review before consolidation.</p>"
        )
    parts.append("</div>")
    return "".join(parts)


def _redundancy_table(clusters: list[RedundancyCluster], heading: str, limit: int = 30) -> str:
    if not clusters:
        return ""
    parts: list[str] = [f"<h3>{_h(heading)}</h3>"]
    parts.append(
        "<table><thead><tr>"
        "<th>Cluster size</th>"
        "<th class='num'>Mean Jaccard</th>"
        "<th class='num'>Cov files</th>"
        "<th class='num'>Total time</th>"
        "<th class='num'>Droppable</th>"
        "<th>Keep (fastest)</th>"
        "<th>Drop candidates</th>"
        "</tr></thead><tbody>"
    )
    for c in clusters[:limit]:
        keep = c.representative
        drops = c.members[1:]
        drop_html = "<br>".join(
            f"<code class='path'>{_h(m.nodeid)}</code> <span class='num'>({m.duration:.2f}s)</span>" for m in drops[:8]
        )
        if len(drops) > 8:
            drop_html += f"<br><em>… {len(drops) - 8} more</em>"
        parts.append(
            "<tr>"
            f"<td class='num'>{len(c.members)}</td>"
            f"<td class='num'>{c.mean_jaccard:.2f}</td>"
            f"<td class='num'>{c.coverage_size}</td>"
            f"<td class='num'>{c.total_duration:.1f}s</td>"
            f"<td class='num warn'>{c.droppable_duration:.1f}s</td>"
            f"<td><code class='path'>{_h(keep.nodeid)}</code><br><span class='num'>{keep.duration:.2f}s</span></td>"
            f"<td>{drop_html}</td>"
            "</tr>"
        )
    if len(clusters) > limit:
        parts.append(f"<tr><td colspan='7'><em>… {len(clusters) - limit} more clusters</em></td></tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _staleness_table(records: list[TestRecord], heading: str, kind: str, limit: int = 30) -> str:
    if not records:
        return ""
    parts: list[str] = [f"<h3>{_h(heading)}</h3>"]
    parts.append(
        "<table><thead><tr>"
        "<th>Test</th>"
        "<th class='num'>Duration</th>"
        f"<th>{'Status' if kind == 'quarantined' else 'Covered files'}</th>"
        "</tr></thead><tbody>"
    )
    for r in records[:limit]:
        third = _status_badge(r.status) if kind == "quarantined" else str(len(r.coverage_files))
        parts.append(
            "<tr>"
            f"<td><code class='path'>{_h(r.nodeid)}</code></td>"
            f"<td class='num'>{r.duration:.2f}s</td>"
            f"<td class='num'>{third}</td>"
            "</tr>"
        )
    if len(records) > limit:
        parts.append(f"<tr><td colspan='3'><em>… {len(records) - limit} more</em></td></tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _redundancy_section(redundancy: RedundancyAnalysis) -> str:
    if redundancy.drop_count == 0 and not redundancy.near_isomorphs:
        return ""
    parts: list[str] = ["<h2>Drop &amp; review lists</h2>"]
    if redundancy.isomorphs:
        parts.append(
            _redundancy_table(
                redundancy.isomorphs,
                f"Isomorphs — identical coverage ({len(redundancy.isomorphs)} clusters, {_fmt_h(sum(c.droppable_duration for c in redundancy.isomorphs))} droppable)",
            )
        )
    if redundancy.quarantined:
        parts.append(
            _staleness_table(
                redundancy.quarantined,
                f"Quarantined — skipped tests still costing collection ({len(redundancy.quarantined)} tests, {_fmt_h(sum(r.duration for r in redundancy.quarantined))})",
                kind="quarantined",
            )
        )
    if redundancy.trivial:
        parts.append(
            _staleness_table(
                redundancy.trivial,
                f"Trivial coverage — only test-helpers, no production code ({len(redundancy.trivial)} tests, {_fmt_h(sum(r.duration for r in redundancy.trivial))})",
                kind="trivial",
            )
        )
    if redundancy.near_isomorphs:
        parts.append(
            _redundancy_table(
                redundancy.near_isomorphs,
                f"Near-isomorphs — Jaccard ≥ 0.85 ({len(redundancy.near_isomorphs)} clusters, {_fmt_h(redundancy.review_savings)} potential — human review)",
            )
        )
    return "".join(parts)


def _parametrization_cluster(members: list[TestRecord]) -> list[tuple[str, list[TestRecord]]]:
    """Group test records by their parametrization base name."""
    by_base: dict[str, list[TestRecord]] = defaultdict(list)
    for r in members:
        by_base[r.base_name].append(r)
    return sorted(by_base.items(), key=lambda kv: -sum(r.duration for r in kv[1]))


def render_html(
    records: list[TestRecord],
    segments: list[Segment],
    aggs: Aggregations,
    shards: list[ShardRecord],
    redundancy: RedundancyAnalysis | None = None,
) -> str:
    total = aggs.total_time
    parts: list[str] = []
    parts.append("<!doctype html><html><head><meta charset='utf-8'>")
    parts.append("<title>Test suite analysis</title>")
    parts.append(f"<style>{CSS}</style></head><body><div class='container'>")
    parts.append("<h1>Test suite analysis</h1>")
    parts.append(
        f"<p class='subtitle'>{len(records):,} tests · "
        f"single-threaded test-time {_fmt_h(total)} · "
        f"median {_fmt_ms(aggs.median)}, p95 {aggs.p95:.2f}s, p99 {aggs.p99:.2f}s, "
        f"max {aggs.max_time:.1f}s</p>"
    )

    # Executive summary up front.
    parts.append(_exec_summary(records, segments, shards))

    # Redundancy & staleness headline — shows drop savings before anything else.
    if redundancy is not None:
        parts.append(_redundancy_banner(redundancy))

    # Headline cards.
    cards = [
        _card("Tests", f"{len(records):,}"),
        _card("Total test-time", _fmt_h(total), "single-threaded sum"),
        _card("50% of time in", f"{aggs.pareto_50:,} tests", f"{100 * aggs.pareto_50 / len(records):.1f}% of suite"),
        _card("80% of time in", f"{aggs.pareto_80:,} tests", f"{100 * aggs.pareto_80 / len(records):.1f}% of suite"),
    ]
    if shards:
        wall = sum(sh.suite_time for sh in shards)
        tc_sum = sum(sh.testcase_sum for sh in shards)
        overhead = wall - tc_sum
        cards.extend(
            [
                _card("CI wall (sum)", _fmt_h(wall), f"{len(shards)} shards"),
                _card("Testcase sum", _fmt_h(tc_sum), f"{100 * tc_sum / wall:.1f}% of wall"),
                _card(
                    "Setup overhead",
                    _fmt_h(overhead),
                    f"{100 * overhead / wall:.1f}% of wall",
                    warn=overhead / wall > 0.5,
                ),
                _card(
                    "Slowest/fastest shard",
                    f"{max(sh.suite_time for sh in shards) / min(sh.suite_time for sh in shards):.1f}×",
                    f"{min(sh.suite_time for sh in shards):.0f}s – {max(sh.suite_time for sh in shards):.0f}s",
                ),
            ]
        )
    cov_records = [r for r in records if r.has_coverage]
    if cov_records:
        overbroad = sum(1 for r in cov_records if r.is_overbroad)
        cards.extend(
            [
                _card(
                    "Coverage data",
                    f"{len(cov_records):,} tests",
                    f"{100 * len(cov_records) / len(records):.1f}% of suite",
                ),
                _card(
                    "Over-broad tracers",
                    f"{overbroad:,}",
                    f">{OVERBROAD_FILE_THRESHOLD} files — bootstrap artifacts",
                ),
            ]
        )
    parts.append(f"<div class='cards'>{''.join(cards)}</div>")

    # Shard balance.
    if shards:
        parts.append("<h2>Shard balance &amp; setup overhead</h2>")
        parts.append(
            "<div class='legend'>"
            "<span><span class='sw testcase'></span>Testcase time</span>"
            "<span><span class='sw overhead'></span>Setup / teardown / fixtures</span>"
            "</div>"
        )
        parts.append(_shard_bars(shards))
        parts.append(
            "<p class='footnote'>Each bar is one shard. Width = suite wall time. "
            "Blue = sum of testcase times; pink = the gap (fixtures, DB migrations, "
            "container startup, teardown). High pink % means the shard is dominated "
            "by setup, not test execution.</p>"
        )
        # Detailed table for top-overhead shards
        parts.append("<h3>Top shards by setup overhead</h3>")
        parts.append(
            "<table><thead><tr><th>Shard</th>"
            "<th class='num'>Suite wall</th><th class='num'>Testcase sum</th>"
            "<th class='num'>Overhead</th><th class='num'>Overhead %</th>"
            "<th class='num'>Tests</th><th class='num'>Skips</th></tr></thead><tbody>"
        )
        for sh in sorted(shards, key=lambda x: -x.overhead)[:15]:
            parts.append(
                f"<tr><td class='path'>{_h(sh.name)}</td>"
                f"<td class='num'>{sh.suite_time:.0f}s</td>"
                f"<td class='num'>{sh.testcase_sum:.0f}s</td>"
                f"<td class='num'>{sh.overhead:.0f}s</td>"
                f"<td class='num'>{sh.overhead_pct:.1f}%</td>"
                f"<td class='num'>{sh.test_count}</td>"
                f"<td class='num'>{sh.skip_count}</td></tr>"
            )
        parts.append("</tbody></table>")

    # Drop & review lists (redundancy + staleness) — actionable.
    if redundancy is not None:
        parts.append(_redundancy_section(redundancy))

    # Archetype segments (color-coded with action labels).
    parts.append("<h2>Archetype segments</h2>")
    parts.append(
        "<p class='footnote'>Each test lands in exactly one bucket. Rows are color-coded by recommended action: "
        "<span class='act act-drop'>drop</span> = strongest pruning candidate; "
        "<span class='act act-opt'>optimize</span> = slow but valuable; "
        "<span class='act act-keep'>keep</span> = workhorse; "
        "<span class='act act-low'>low priority</span> = no value to optimize; "
        "<span class='act act-data'>data</span> = ignore for now (measurement noise / missing input).</p>"
    )
    parts.append(
        "<table><thead><tr><th>Action</th><th>Segment</th><th class='num'>Tests</th>"
        "<th class='num'>Total time</th><th class='num'>% of recorded</th>"
        "<th>Description</th></tr></thead><tbody>"
    )
    for s in segments:
        pct = 100 * s.total_time / total if total else 0
        parts.append(
            f"<tr class='{_action_row_class(s.name)}'>"
            f"<td>{_action_badge(s.name)}</td>"
            f"<td><code>{_h(s.name)}</code></td>"
            f"<td class='num'>{s.count:,}</td>"
            f"<td class='num'>{_fmt_h(s.total_time)}</td>"
            f"<td class='num'>{pct:.1f}%</td>"
            f"<td>{_h(s.description)}</td></tr>"
        )
    parts.append("</tbody></table>")

    # Per-segment drill-down. For drop/optimize segments, group by base test name
    # so over-parametrized families show as one row rather than dozens.
    actionable = {"slow_dispensable", "slow_irreplaceable"}
    for s in segments:
        if not s.members or s.name in {"fast_valuable", "fast_broad_only"}:
            continue  # only deep-dive on actionable + data-issue buckets
        if s.name in actionable:
            clusters = _parametrization_cluster(s.members)
            multi = [(b, rs) for b, rs in clusters if len(rs) > 1]
            singles = [(b, rs) for b, rs in clusters if len(rs) == 1]
            details_open = " open" if s.name == "slow_dispensable" else ""
            parts.append(
                f"<details{details_open}><summary>{_action_badge(s.name)} {_h(s.name)} — {s.count:,} tests, {_fmt_h(s.total_time)}</summary>"
            )
            if multi:
                parts.append("<h3>Parametrization clusters (group by base test)</h3>")
                parts.append(
                    "<table><thead><tr><th>Base test</th>"
                    "<th class='num'>Variants</th><th class='num'>Total time</th>"
                    "<th class='num'>Mean</th><th class='num'>Mean files</th>"
                    "<th class='num'>Mean invFreq</th></tr></thead><tbody>"
                )
                for base, rs in multi[:20]:
                    tot = sum(r.duration for r in rs)
                    mean_files = sum(r.files_touched for r in rs) / len(rs)
                    mean_inv = sum(r.inv_freq for r in rs) / len(rs)
                    parts.append(
                        f"<tr><td class='path'>{_h(base)}</td>"
                        f"<td class='num'>{len(rs)}</td>"
                        f"<td class='num'>{_fmt_h(tot)}</td>"
                        f"<td class='num'>{tot / len(rs):.2f}s</td>"
                        f"<td class='num'>{mean_files:.0f}</td>"
                        f"<td class='num'>{mean_inv:.2f}</td></tr>"
                    )
                parts.append("</tbody></table>")
            if singles:
                parts.append("<h3>Individual tests (no parametrization)</h3>")
                parts.append(
                    "<table><thead><tr><th class='num'>Duration</th><th>Test</th>"
                    "<th class='num'>Files</th><th class='num'>invFreq</th>"
                    "<th class='num'>min others</th></tr></thead><tbody>"
                )
                for _, rs in sorted(singles, key=lambda kv: -kv[1][0].duration)[:25]:
                    r = rs[0]
                    parts.append(
                        f"<tr><td class='num'>{r.duration:.2f}s</td>"
                        f"<td class='path'>{_h(r.nodeid)}</td>"
                        f"<td class='num'>{r.files_touched}</td>"
                        f"<td class='num'>{r.inv_freq:.2f}</td>"
                        f"<td class='num'>{r.min_others}</td></tr>"
                    )
                parts.append("</tbody></table>")
            parts.append("</details>")
        else:
            # Data-issue segments: simple top-25 list, collapsed.
            parts.append(
                f"<details><summary>{_action_badge(s.name)} {_h(s.name)} — {s.count:,} tests, {_fmt_h(s.total_time)}</summary>"
            )
            parts.append("<table><thead><tr><th class='num'>Duration</th><th>Test</th></tr></thead><tbody>")
            for r in sorted(s.members, key=lambda x: -x.duration)[:25]:
                parts.append(f"<tr><td class='num'>{r.duration:.2f}s</td><td class='path'>{_h(r.nodeid)}</td></tr>")
            parts.append("</tbody></table></details>")

    # Cluster view: resource consumption by product / feature area.
    if aggs.by_cluster:
        parts.append("<h2>Resource consumption by cluster (product or feature area)</h2>")
        parts.append(
            "<p class='footnote'>Tests grouped by their first 2–3 path segments: "
            "<code>products/&lt;name&gt;</code> for product apps, "
            "<code>posthog/&lt;area&gt;/&lt;sub&gt;</code> for core features, "
            "<code>ee/&lt;area&gt;</code> for enterprise add-ons. "
            "<strong>Unique files</strong> is the union of source files all the cluster's tests touch (testmon). "
            "<strong>Files/hour</strong> is unique_files / total_time — higher = more code covered per minute of CI. "
            "<strong>Mean invFreq</strong> averages each test's rarity-weighted coverage; lower = the cluster mostly covers commonly-tested code.</p>"
        )
        # Top 25 by total time (the biggest CI sinks)
        parts.append("<h3>Biggest CI cost (top 25 by total time)</h3>")
        parts.append(
            "<table><thead><tr><th>Cluster</th>"
            "<th class='num'>Tests</th><th class='num'>Total time</th>"
            "<th class='num'>Mean</th><th class='num'>Testmon coverage</th>"
            "<th class='num'>Unique files</th><th class='num'>Files/hour</th>"
            "<th class='num'>Mean invFreq</th></tr></thead><tbody>"
        )
        for c in aggs.by_cluster[:25]:
            cov_pct = (100 * c.cov_count / c.test_count) if c.test_count else 0
            cov_warn = "" if cov_pct >= 80 else " title='Coverage data missing for many tests'"
            fph = f"{c.files_per_hour:.0f}" if c.files_per_hour > 0 else "—"
            inv = f"{c.mean_inv_freq:.2f}" if c.mean_inv_freq > 0 else "—"
            uniq = f"{c.unique_files:,}" if c.unique_files > 0 else "—"
            parts.append(
                f"<tr><td class='path'>{_h(c.name)}</td>"
                f"<td class='num'>{c.test_count:,}</td>"
                f"<td class='num'>{_fmt_h(c.total_time)}</td>"
                f"<td class='num'>{c.mean_duration:.2f}s</td>"
                f"<td class='num'{cov_warn}>{cov_pct:.0f}%</td>"
                f"<td class='num'>{uniq}</td>"
                f"<td class='num'>{fph}</td>"
                f"<td class='num'>{inv}</td></tr>"
            )
        parts.append("</tbody></table>")

        # Sort by *redundancy* — lowest mean_inv_freq (clusters spending lots
        # of test time on commonly-tested code). Filter to clusters with
        # actual coverage data (≥80% cov) and meaningful size.
        red_candidates = [
            c for c in aggs.by_cluster if c.cov_count > 30 and (c.cov_count / max(c.test_count, 1)) >= 0.8
        ]
        red_candidates.sort(key=lambda c: c.mean_inv_freq)
        if red_candidates:
            parts.append("<h3>Most redundant clusters (low coverage rarity, big size)</h3>")
            parts.append(
                "<p class='footnote'>Clusters with high coverage % (so the data is reliable) "
                "and the <em>lowest</em> mean invFreq — meaning their tests mostly cover code "
                "that many other tests also cover. Candidates for "
                "<em>fewer tests, same effective coverage</em>.</p>"
            )
            parts.append(
                "<table><thead><tr><th>Cluster</th>"
                "<th class='num'>Tests</th><th class='num'>Total time</th>"
                "<th class='num'>Mean invFreq</th><th class='num'>Unique files</th>"
                "<th class='num'>Tests / unique file</th></tr></thead><tbody>"
            )
            for c in red_candidates[:15]:
                tpf = (c.cov_count / c.unique_files) if c.unique_files > 0 else 0
                parts.append(
                    f"<tr><td class='path'>{_h(c.name)}</td>"
                    f"<td class='num'>{c.test_count:,}</td>"
                    f"<td class='num'>{_fmt_h(c.total_time)}</td>"
                    f"<td class='num'>{c.mean_inv_freq:.2f}</td>"
                    f"<td class='num'>{c.unique_files:,}</td>"
                    f"<td class='num'>{tpf:.1f}</td></tr>"
                )
            parts.append("</tbody></table>")

        # Efficiency view: files/hour. Filter to clusters with coverage.
        eff = [c for c in aggs.by_cluster if c.files_per_hour > 0 and c.cov_count > 30]
        eff.sort(key=lambda c: c.files_per_hour)
        if eff:
            parts.append("<h3>Lowest coverage efficiency (fewest files covered per hour of test time)</h3>")
            parts.append(
                "<p class='footnote'>Clusters spending the most test time per unique file covered. "
                "Could mean: legitimately expensive code paths (ClickHouse, Temporal workflows), "
                "or unnecessary repetition of the same logic.</p>"
            )
            parts.append(
                "<table><thead><tr><th>Cluster</th>"
                "<th class='num'>Tests</th><th class='num'>Total time</th>"
                "<th class='num'>Unique files</th><th class='num'>Files/hour</th>"
                "<th class='num'>Sec/file</th></tr></thead><tbody>"
            )
            for c in eff[:15]:
                spf = c.total_time / c.unique_files if c.unique_files > 0 else 0
                parts.append(
                    f"<tr><td class='path'>{_h(c.name)}</td>"
                    f"<td class='num'>{c.test_count:,}</td>"
                    f"<td class='num'>{_fmt_h(c.total_time)}</td>"
                    f"<td class='num'>{c.unique_files:,}</td>"
                    f"<td class='num'>{c.files_per_hour:.0f}</td>"
                    f"<td class='num'>{spf:.0f}s</td></tr>"
                )
            parts.append("</tbody></table>")

    # Hottest packages.
    parts.append("<h2>Hottest packages</h2>")
    parts.append(
        "<table><thead><tr><th>Package</th><th class='num'>Tests</th>"
        "<th class='num'>Total</th><th class='num'>Mean</th>"
        "<th class='num'>Median</th></tr></thead><tbody>"
    )
    for name, total_t, count, med in aggs.by_package[:25]:
        parts.append(
            f"<tr><td class='path'>{_h(name)}</td>"
            f"<td class='num'>{count:,}</td>"
            f"<td class='num'>{_fmt_h(total_t)}</td>"
            f"<td class='num'>{total_t / count:.2f}s</td>"
            f"<td class='num'>{_fmt_ms(med)}</td></tr>"
        )
    parts.append("</tbody></table>")

    # Slowest classes.
    parts.append("<h2>Slowest classes</h2>")
    parts.append(
        "<table><thead><tr><th>Class</th><th class='num'>Tests</th>"
        "<th class='num'>Total</th><th class='num'>Mean</th></tr></thead><tbody>"
    )
    for cid, total_t, count in aggs.by_class[:25]:
        parts.append(
            f"<tr><td class='path'>{_h(cid)}</td>"
            f"<td class='num'>{count}</td>"
            f"<td class='num'>{_fmt_h(total_t)}</td>"
            f"<td class='num'>{total_t / count:.2f}s</td></tr>"
        )
    parts.append("</tbody></table>")

    # Parametrization explosion.
    if aggs.by_base:
        parts.append("<h2>Parametrization explosion</h2>")
        parts.append(
            "<p class='footnote'>Base tests (without <code>[param]</code> suffix) "
            "with the most parameter variants. Many variants × non-trivial time per "
            "variant is a strong pruning candidate — most parametrized tests have "
            "diminishing fault-detection value past a handful of cases.</p>"
        )
        parts.append(
            "<table><thead><tr><th>Base test</th><th class='num'>Param count</th>"
            "<th class='num'>Total time</th><th class='num'>Mean per param</th></tr></thead><tbody>"
        )
        for base, n, total_t in aggs.by_base[:25]:
            parts.append(
                f"<tr><td class='path'>{_h(base)}</td>"
                f"<td class='num'>{n}</td>"
                f"<td class='num'>{_fmt_h(total_t)}</td>"
                f"<td class='num'>{total_t / n:.2f}s</td></tr>"
            )
        parts.append("</tbody></table>")

    # Status mix.
    if aggs.status_counts and set(aggs.status_counts) - {"unknown"}:
        parts.append("<h2>Status mix (from junit)</h2>")
        parts.append("<table><thead><tr><th>Status</th><th class='num'>Count</th></tr></thead><tbody>")
        for st, n in aggs.status_counts.most_common():
            parts.append(f"<tr><td>{_status_badge(st) or _h(st)}</td><td class='num'>{n:,}</td></tr>")
        parts.append("</tbody></table>")

    # Methods / how to read this footer.
    parts.append(
        "<div class='methods'><h3>How to read this report</h3>"
        "<dl>"
        "<dt>Duration source</dt>"
        "<dd><code>.test_durations</code> (pytest-split): smoothed averages across master runs, clamped to a 10ms floor; "
        "flat 60.0/18.0 entries are <em>defaults</em> (newly added tests, flaky reruns), not real timings — bucketed as <em>untrusted timing</em>. "
        "Per-test junit timings from this run are more accurate but only cover tests that actually ran; "
        "<code>.test_durations</code> includes everything pytest-split has ever balanced for. Treat the duration figures here as historical averages, not single-run truth.</dd>"
        "<dt>Coverage source</dt>"
        "<dd>pytest-testmon (<code>.testmondata</code>): per-shard SQLite recording which source files each test imported during execution. "
        "File-level, not line-level. Merged across 46 shards. Files in <code>tools/testmon_high_fanout_files.txt</code> "
        "(settings, conftest, DB routers, etc. touched by ~every test) are discounted from each test's set.</dd>"
        "<dt>invFreq score</dt>"
        "<dd>For each file <em>f</em> a test touches, add <em>1 / N</em> where <em>N</em> is the number of tests touching <em>f</em>. "
        "Higher = test contributes coverage of rarer files. Score 0.1 ≈ all my files are heavily-tested elsewhere; "
        "score &gt; 1.0 ≈ I cover code few other tests touch.</dd>"
        "<dt>min others</dt>"
        "<dd>For the rarest-covered file in the test's set, how many <em>other</em> tests also touch it. 0 = test is the only one covering at least one file.</dd>"
        "<dt>Slow / fast cutoff</dt>"
        '<dd>p99 of trustworthy durations. "Slow" means top-1% by duration, not just above-average.</dd>'
        "<dt>Unique / broad cutoff</dt>"
        '<dd>Median invFreq across tests with valid coverage. "Unique" = above-median rarity-weighted coverage.</dd>'
        "<dt>Suite wall vs testcase sum</dt>"
        "<dd>Wall = junit <code>testsuite time</code> per shard (includes fixture/migration/teardown overhead). "
        "Testcase sum = sum of individual <code>testcase time</code> in that shard. "
        "Their difference is overhead — fixture setup, DB migrations, container boot.</dd>"
        "<dt>Known data gaps</dt>"
        "<dd>Turbo-tests Products job doesn't currently upload <code>.testmondata</code> (workflow path mismatch); "
        "6 Core-poe1 shards produced empty SQLite files. Both are fixable in the workflow.</dd>"
        "</dl></div>"
    )

    parts.append("</div></body></html>")
    return "".join(parts)


# ---- entrypoint -------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--durations", type=Path, default=DURATIONS_PATH)
    parser.add_argument(
        "--junit-dir",
        type=Path,
        help="Directory tree of junit XMLs (CI artifact download). Enables shard/overhead analysis.",
    )
    parser.add_argument(
        "--testmon-dir",
        type=Path,
        help="Directory of per-shard .testmondata SQLite files. Enables coverage-aware archetype segmentation.",
    )
    parser.add_argument(
        "--high-fanout",
        type=Path,
        default=HIGH_FANOUT_PATH,
        help="File listing source files to discount as common infrastructure (default: tools/testmon_high_fanout_files.txt).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write report here. Extension picks format: .html (rich), .md (default).",
    )
    args = parser.parse_args()

    durations = load_durations(args.durations)
    junit_status, shards = parse_junit_dir(args.junit_dir) if args.junit_dir else ({}, [])
    high_fanout = load_high_fanout(args.high_fanout) if args.testmon_dir else set()
    test_files = load_testmon_dir(args.testmon_dir, high_fanout) if args.testmon_dir else {}
    records = build_records(durations, junit_status, test_files)
    # Use coverage-aware segmentation when testmon data joins meaningfully (>1% of tests).
    cov_records = sum(1 for r in records if r.has_coverage)
    if cov_records > len(records) * 0.01:
        segments = segment_by_coverage(records)
    else:
        segments = segment_records(records)
    aggs = compute_aggregations(records, test_files=test_files or None)
    redundancy = analyze_redundancy(records)

    fmt = "html" if (args.out and args.out.suffix.lower() in {".html", ".htm"}) else "md"
    render = render_html if fmt == "html" else render_markdown
    report = render(records, segments, aggs, shards, redundancy)

    if args.out:
        args.out.write_text(report)
        sys.stderr.write(f"wrote {args.out} ({fmt})\n")
    else:
        sys.stdout.write(report + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
