"""Turn the per-test resource profile into a rich test-waste report.

Consumes the JSONL written by tools/pytest_resource_profiler (one row per test).
Two kinds of finding:

Conversion opportunities (binary candidates — verify before acting):
  - no-DB         : DB set up, zero Postgres + ClickHouse queries  -> SimpleTestCase
  - CH-unused     : ClickHouse mixin, zero ClickHouse queries      -> drop the mixin
  - txn-downgrade : TransactionTestCase, no on_commit / FOR UPDATE / 2nd conn / async -> TestCase
  - multi-DB-trim : `databases` declares an alias the test never queries -> trim it

Overuse & redundancy rankings (where setup cost concentrates):
  - setup-heavy   : most of a test's queries are setup, not the test body
  - redundant-setup (N+1): one query shape repeated many times during setup
  - over-provisioned: very high total query count (heavy fixtures)

Self-sufficient: per-test wall time and status come from the plugin, so no junit
or coverage correlation is needed.

Usage:
    python tools/test_resource_report.py --in logs/resource_profile.jsonl
    python tools/test_resource_report.py --in logs/resource_profile.jsonl --out logs/test_waste.html
"""

from __future__ import annotations

import sys
import html
import json
import argparse
from collections import Counter, defaultdict
from pathlib import Path

# Thresholds for the ranked overuse buckets. Conservative so the lists stay actionable.
SETUP_HEAVY_MIN_Q = 30
SETUP_HEAVY_RATIO = 0.7
REDUNDANT_DUP_MIN = 10
OVERPROVISIONED_MIN_Q = 100

CONVERSION_LABELS = {
    "no_db": ("DB set up, 0 queries", "SimpleTestCase"),
    "ch_unused": ("ClickHouse mixin, 0 CH queries", "drop CH mixin"),
    "txn_downgrade": ("TransactionTestCase, no txn need", "TestCase"),
    "multi_db_trim": ("`databases` over-declared", "trim databases"),
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


def class_key(nodeid: str) -> str:
    """file::Class for grouping (setUpTestData is class-level); falls back to the file."""
    parts = nodeid.split("::")
    if len(parts) >= 2:
        return "::".join(parts[:2])
    return parts[0]


def short_path(path: str) -> str:
    for marker in ("/posthog/", "/products/", "/ee/"):
        if marker in path:
            return marker.strip("/") + "/" + path.split(marker, 1)[-1]
    return path


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


def bucket_setup_heavy(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        total = r.get("pg_total", 0)
        setup = r.get("pg_setup", 0)
        if setup >= SETUP_HEAVY_MIN_Q and total > 0 and setup / total >= SETUP_HEAVY_RATIO:
            out.append(r)
    return out


def bucket_redundant_setup(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("setup_max_dup", 0) >= REDUNDANT_DUP_MIN]


def bucket_over_provisioned(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("pg_total", 0) >= OVERPROVISIONED_MIN_Q]


def summarize(rows: list[dict]) -> dict:
    return {
        "no_db": bucket_no_db(rows),
        "ch_unused": bucket_ch_unused(rows),
        "txn_downgrade": bucket_txn_downgrade(rows),
        "multi_db_trim": bucket_multi_db_trim(rows),
        "setup_heavy": bucket_setup_heavy(rows),
        "redundant_setup": bucket_redundant_setup(rows),
        "over_provisioned": bucket_over_provisioned(rows),
    }


def bucket_time(bucket: list[dict]) -> float:
    return sum(r.get("duration_s", 0.0) for r in bucket)


def top_files(bucket: list[dict], n: int = 15) -> list[tuple[str, int, float]]:
    counts: Counter[str] = Counter()
    times: dict[str, float] = defaultdict(float)
    for r in bucket:
        f = r["file"]
        counts[f] += 1
        times[f] += r.get("duration_s", 0.0)
    ranked = sorted(counts.items(), key=lambda kv: -times[kv[0]])
    return [(f, c, times[f]) for f, c in ranked[:n]]


def top_classes(bucket: list[dict], metric: str, n: int = 20) -> list[tuple[str, int, int, int]]:
    """Group by file::Class. Returns (class_key, ntests, summed_metric, summed_setup)."""
    agg: dict[str, dict] = defaultdict(lambda: {"n": 0, "metric": 0, "setup": 0})
    for r in bucket:
        k = class_key(r["nodeid"])
        agg[k]["n"] += 1
        agg[k]["metric"] += r.get(metric, 0)
        agg[k]["setup"] += r.get("pg_setup", 0)
    ranked = sorted(agg.items(), key=lambda kv: -kv[1]["metric"])
    return [(k, v["n"], v["metric"], v["setup"]) for k, v in ranked[:n]]


def stats(rows: list[dict]) -> dict:
    db_rows = [r for r in rows if r.get("db_enabled")]
    return {
        "total": len(rows),
        "db_enabled": len(db_rows),
        "wall": sum(r.get("duration_s", 0.0) for r in rows),
        "pg_total": sum(r.get("pg_total", 0) for r in rows),
        "pg_setup": sum(r.get("pg_setup", 0) for r in rows),
        "ch_total": sum(r.get("ch_call", 0) for r in rows),
    }


# ---------------------------------------------------------------- markdown


def format_markdown(rows: list[dict], buckets: dict) -> str:
    s = stats(rows)
    out: list[str] = ["# Test resource-waste report\n"]
    out.append(f"- Tests profiled: **{s['total']:,}** ({s['db_enabled']:,} DB-enabled)")
    out.append(f"- Postgres queries: **{s['pg_total']:,}** ({s['pg_setup']:,} in setup)")
    out.append(f"- ClickHouse queries: **{s['ch_total']:,}** · call wall-time **{fmt_dur(s['wall'])}**")
    out.append("- No junit/coverage correlation — the profiler records timing + status itself\n")

    out.append("## Conversion opportunities\n")
    out.append("| candidate | tests | call wall-time | fix |")
    out.append("|---|---:|---:|---|")
    for key, (desc, fix) in CONVERSION_LABELS.items():
        b = buckets[key]
        out.append(f"| {desc} | {len(b):,} | {fmt_dur(bucket_time(b))} | -> {fix} |")
    out.append("\n_Candidates only — confirm each (esp. txn-downgrade) by converting and re-running._\n")

    for key, (desc, _fix) in CONVERSION_LABELS.items():
        b = buckets[key]
        if not b:
            continue
        out.append(f"\n### {desc} — {len(b):,} tests\n")
        out.append("by base: " + ", ".join(f"{base}={n}" for base, n in Counter(r["base"] for r in b).most_common()))
        for f, c, t in top_files(b):
            extra = ""
            if key == "multi_db_trim":
                sample = next((r for r in b if r["file"] == f), {})
                extra = f"  (unused: {','.join(sample.get('_unused_dbs', []))})"
            out.append(f"- {c:3d}  {fmt_dur(t):>7}  {short_path(f)}{extra}")

    out.append("\n## Overuse & redundancy (setup cost)\n")
    overuse = [
        ("setup-heavy (setup >> body)", "setup_heavy", "pg_setup"),
        ("redundant setup (N+1 fixtures)", "redundant_setup", "setup_max_dup"),
        ("over-provisioned (heavy total)", "over_provisioned", "pg_total"),
    ]
    for title, key, metric in overuse:
        b = buckets[key]
        out.append(f"\n### {title} — {len(b):,} tests\n")
        for k, n, m, setup in top_classes(b, metric):
            out.append(f"- {n:3d} tests  {metric}={m:,} (setup {setup:,})  {short_path(k)}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- html

_CSS = """
:root{--fg:#0f172a;--muted:#64748b;--line:#e2e8f0;--card:#fff;--bg:#f8fafc;--accent:#0ea5e9;--warn:#dc2626;--ok:#16a34a}
*{box-sizing:border-box}
body{font:14px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:var(--fg);background:var(--bg);margin:0;padding:28px}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:34px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:14px;margin:20px 0 8px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.sub{color:var(--muted);margin:0 0 22px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.card .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}
.card .v{font-size:22px;font-weight:650;margin-top:4px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;margin:8px 0 4px;font-size:13px}
th,td{text-align:left;padding:7px 11px;border-bottom:1px solid var(--line)}
th{background:#f1f5f9;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--muted)}
tr:last-child td{border-bottom:none}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:#334155}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600}
.pill.go{background:#dcfce7;color:#166534}
.note{color:var(--muted);font-size:12.5px;margin:6px 0 0}
"""


def _esc(s: str) -> str:
    return html.escape(str(s))


def _table(headers: list[str], rows: list[list], aligns: list[str]) -> str:
    th = "".join(f"<th class='{a}'>{_esc(h)}</th>" for h, a in zip(headers, aligns))
    body = []
    for row in rows:
        tds = "".join(f"<td class='{a}'>{cell}</td>" for cell, a in zip(row, aligns))
        body.append(f"<tr>{tds}</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def format_html(rows: list[dict], buckets: dict) -> str:
    s = stats(rows)
    parts: list[str] = []
    parts.append("<!doctype html><html lang='en'><head><meta charset='utf-8'>")
    parts.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    parts.append("<title>Test resource-waste report</title>")
    parts.append(f"<style>{_CSS}</style></head><body><div class='wrap'>")
    parts.append("<h1>Test resource-waste report</h1>")
    parts.append(
        "<p class='sub'>What each test provisioned vs. what it used. "
        "Per-test timing and status captured directly &mdash; no junit or coverage correlation.</p>"
    )

    cards = [
        ("tests profiled", f"{s['total']:,}"),
        ("DB-enabled", f"{s['db_enabled']:,}"),
        ("postgres queries", f"{s['pg_total']:,}"),
        ("of which setup", f"{s['pg_setup']:,}"),
        ("clickhouse queries", f"{s['ch_total']:,}"),
        ("call wall-time", fmt_dur(s["wall"])),
    ]
    parts.append("<div class='cards'>")
    for k, v in cards:
        parts.append(f"<div class='card'><div class='k'>{_esc(k)}</div><div class='v'>{_esc(v)}</div></div>")
    parts.append("</div>")

    # Conversion opportunities summary
    parts.append("<h2>Conversion opportunities</h2>")
    summ_rows = []
    for key, (desc, fix) in CONVERSION_LABELS.items():
        b = buckets[key]
        summ_rows.append(
            [desc, f"{len(b):,}", fmt_dur(bucket_time(b)), f"<span class='pill go'>&rarr; {_esc(fix)}</span>"]
        )
    parts.append(_table(["candidate", "tests", "call wall-time", "fix"], summ_rows, ["", "n", "n", ""]))
    parts.append(
        "<p class='note'>Candidates only. Confirm each &mdash; especially txn-downgrade &mdash; "
        "by converting and re-running before changing anything.</p>"
    )

    for key, (desc, _fix) in CONVERSION_LABELS.items():
        b = buckets[key]
        if not b:
            continue
        by_base = ", ".join(f"{_esc(base)}={n}" for base, n in Counter(r["base"] for r in b).most_common())
        parts.append(f"<h3>{_esc(desc)} &mdash; {len(b):,} tests <span class='note'>({by_base})</span></h3>")
        file_rows = []
        for f, c, t in top_files(b):
            extra = ""
            if key == "multi_db_trim":
                sample = next((r for r in b if r["file"] == f), {})
                extra = f" <code>unused: {_esc(','.join(sample.get('_unused_dbs', [])))}</code>"
            file_rows.append([f"{c}", fmt_dur(t), f"<code>{_esc(short_path(f))}</code>{extra}"])
        parts.append(_table(["tests", "wall", "file"], file_rows, ["n", "n", ""]))

    # Overuse & redundancy
    parts.append("<h2>Overuse &amp; redundancy (setup cost)</h2>")
    overuse = [
        ("Setup-heavy (setup &gt;&gt; body)", "setup_heavy", "pg_setup", "setup queries"),
        ("Redundant setup (N+1 fixtures)", "redundant_setup", "setup_max_dup", "max repeats of one query"),
        ("Over-provisioned (heavy total)", "over_provisioned", "pg_total", "total queries"),
    ]
    for title, key, metric, col in overuse:
        b = buckets[key]
        parts.append(f"<h3>{title} &mdash; {len(b):,} tests</h3>")
        cls_rows = []
        for k, n, m, setup in top_classes(b, metric):
            cls_rows.append([f"{n}", f"{m:,}", f"{setup:,}", f"<code>{_esc(short_path(k))}</code>"])
        parts.append(_table(["tests", col, "setup q", "class"], cls_rows, ["n", "n", "n", ""]))

    parts.append(
        "<p class='note'>Setup-heavy / redundant point at fixtures rebuilt per test "
        "(move read-only data to setUpTestData) or N+1 in fixture creation.</p>"
    )
    parts.append("</div></body></html>")
    return "".join(parts)


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
