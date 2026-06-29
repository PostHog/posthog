"""Turn the per-test resource profile into ranked test-waste reports.

Consumes the JSONL written by tools/pytest_resource_profiler (one row per test)
and emits four "provisioned but unused" buckets, each ranked by where the time goes:

  - no-DB         : DB set up, zero Postgres + ClickHouse queries  -> SimpleTestCase
  - CH-unused     : ClickHouse mixin, zero ClickHouse queries      -> drop the mixin
  - txn-downgrade : TransactionTestCase with no on_commit / FOR UPDATE / 2nd connection -> TestCase
  - multi-DB-trim : `databases` declares an alias the test never queries -> trim it

Self-sufficient: the profile already carries per-test wall time and status, so no
junit or coverage correlation is needed.

Usage:
    python tools/test_resource_report.py --in logs/resource_profile.jsonl
    python tools/test_resource_report.py --in logs/resource_profile.jsonl --out logs/test_waste.md
    python tools/test_resource_report.py --in logs/resource_profile.jsonl --out logs/test_waste.html
"""

from __future__ import annotations

import sys
import html
import json
import argparse
from collections import Counter, defaultdict
from pathlib import Path

BUCKET_LABELS = {
    "no_db": ("DB set up, 0 queries", "-> SimpleTestCase"),
    "ch_unused": ("ClickHouse mixin, 0 CH queries", "-> drop CH mixin"),
    "txn_downgrade": ("TransactionTestCase, no txn need", "-> TestCase"),
    "multi_db_trim": ("`databases` over-declared", "-> trim databases"),
}


def fmt_dur(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    if seconds >= 1:
        return f"{seconds:.1f}s"
    return f"{seconds * 1000:.0f}ms"


def used_aliases(row: dict) -> set[str]:
    return {a for a, n in row.get("pg_alias", {}).items() if n > 0}


def is_passing(row: dict) -> bool:
    # Only propose conversions for tests that actually passed in this run.
    return row.get("status") in {"passed", "unknown"}


def load_rows(path: Path) -> list[dict]:
    """Load JSONL, deduping by nodeid (shards/re-runs) keeping the most-exercised row."""
    by_id: dict[str, dict] = {}
    dupes = 0
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        nid = r["nodeid"]
        prev = by_id.get(nid)
        if prev is None:
            by_id[nid] = r
        else:
            dupes += 1
            # Keep whichever observed more datastore activity (a 0-query re-run must not mask a real one).
            if (r.get("pg_total", 0) + r.get("ch_call", 0)) > (prev.get("pg_total", 0) + prev.get("ch_call", 0)):
                by_id[nid] = r
    if dupes:
        sys.stderr.write(f"note: collapsed {dupes} duplicate nodeids (multiple shards/runs)\n")
    return list(by_id.values())


def bucket_no_db(rows: list[dict]) -> list[dict]:
    return [
        r
        for r in rows
        if r.get("db_enabled") and r.get("pg_total", 0) == 0 and r.get("ch_call", 0) == 0 and is_passing(r)
    ]


def bucket_ch_unused(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("ch_provisioned") and r.get("ch_call", 0) == 0 and is_passing(r)]


def bucket_txn_downgrade(rows: list[dict]) -> list[dict]:
    # Heuristic only — async tests need transaction=True for the async/sync ORM boundary, so exclude them.
    # Survivors are CANDIDATES; confirm each by swapping to TestCase and re-running before converting.
    out = []
    for r in rows:
        if not r.get("is_txn") or r.get("is_async") or not is_passing(r):
            continue
        if r.get("on_commit", 0) == 0 and not r.get("for_update") and len(used_aliases(r)) <= 1:
            out.append(r)
    return out


def bucket_multi_db_trim(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        declared = r.get("declared_dbs")
        if not isinstance(declared, list) or len(declared) <= 1:
            continue  # "__all__", None, or single-DB: nothing to trim here
        unused = [d for d in declared if d not in used_aliases(r)]
        if unused:
            out.append({**r, "_unused_dbs": unused})
    return out


def summarize(rows: list[dict]) -> dict:
    return {
        "no_db": bucket_no_db(rows),
        "ch_unused": bucket_ch_unused(rows),
        "txn_downgrade": bucket_txn_downgrade(rows),
        "multi_db_trim": bucket_multi_db_trim(rows),
    }


def bucket_time(bucket: list[dict]) -> float:
    return sum(r.get("duration_s", 0.0) for r in bucket)


def top_files(bucket: list[dict], n: int = 15) -> list[tuple[str, int, float]]:
    by_file_count: Counter[str] = Counter()
    by_file_time: dict[str, float] = defaultdict(float)
    for r in bucket:
        f = r["file"]
        by_file_count[f] += 1
        by_file_time[f] += r.get("duration_s", 0.0)
    ranked = sorted(by_file_count.items(), key=lambda kv: -by_file_time[kv[0]])
    return [(f, c, by_file_time[f]) for f, c in ranked[:n]]


def format_markdown(rows: list[dict], buckets: dict) -> str:
    out: list[str] = []
    out.append("# Test resource-waste report\n")
    out.append(f"- Tests profiled: **{len(rows):,}**")
    db_rows = [r for r in rows if r.get("db_enabled")]
    out.append(f"- DB-enabled tests: **{len(db_rows):,}**")
    out.append("- Call-phase wall time captured directly (no junit/coverage correlation)\n")

    out.append("## Buckets\n")
    out.append("| bucket | tests | call wall-time | fix |")
    out.append("|---|---:|---:|---|")
    for key, (desc, fix) in BUCKET_LABELS.items():
        b = buckets[key]
        out.append(f"| {desc} | {len(b):,} | {fmt_dur(bucket_time(b))} | {fix} |")
    out.append(
        "\n_Wall-time = where these tests currently spend time; realizable saving is the per-test "
        "DB/transaction overhead, a fraction of that. Counts are the actionable signal._\n"
    )

    for key, (desc, _fix) in BUCKET_LABELS.items():
        b = buckets[key]
        if not b:
            continue
        out.append(f"\n## {desc} ({len(b):,} tests, {fmt_dur(bucket_time(b))})\n")
        by_base = Counter(r["base"] for r in b)
        out.append("by base: " + ", ".join(f"{base}={n}" for base, n in by_base.most_common()))
        out.append("\n### Top files by wall-time\n")
        for f, c, t in top_files(b):
            short = f.split("/posthog/", 1)[-1] if "/posthog/" in f else f
            extra = ""
            if key == "multi_db_trim":
                sample = next((r for r in b if r["file"] == f), {})
                extra = f"  (unused: {','.join(sample.get('_unused_dbs', []))})"
            out.append(f"- {c:3d} tests  {fmt_dur(t):>7}  {short}{extra}")
    return "\n".join(out) + "\n"


def format_html(rows: list[dict], buckets: dict) -> str:
    body = html.escape(format_markdown(rows, buckets))
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Test resource-waste report</title>"
        "<style>body{font:14px/1.5 -apple-system,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px}"
        "pre{white-space:pre-wrap}</style></head><body><pre>" + body + "</pre></body></html>"
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None, help="write to file; .html renders HTML, else markdown")
    args = ap.parse_args(argv)

    rows = load_rows(args.inp)
    buckets = summarize(rows)
    text = format_html(rows, buckets) if (args.out and args.out.suffix == ".html") else format_markdown(rows, buckets)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        sys.stdout.write(f"wrote {args.out}\n")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
