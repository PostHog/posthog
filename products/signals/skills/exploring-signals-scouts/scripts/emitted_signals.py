#!/usr/bin/env python3
# ruff: noqa: T201 — CLI tool; stdout/stderr prints are the intended output
"""Render a plain-text table of signals a project's Signals scouts have actually emitted.

Pure formatter — no network I/O. The fleet's run rows carry no emit flag and no finding
count, and the `source_product="signals_scout"` inbox filter doesn't reliably surface scout
findings — so the authoritative record of what a scout *actually emitted* is the emitted
signal itself, in the `document_embeddings` table. You fetch it once with `execute-sql`
through the PostHog MCP (works for any team — this is the general path), save the output to a
file, then point this script at it.

This shows signals that genuinely **landed in the pipeline** (cleared every emit gate).
A scout can narrate "EMITTED ..." in its run summary yet have the emit silently dropped by a
preflight gate (the scout was in dry-run at the time, the org hasn't approved AI processing,
or the `signals_scout` source is disabled) — those never reach this table. So a row here is
ground truth that a finding persisted; a finding a scout *claims* it emitted that is absent
here was gated or failed (itself a useful diagnostic).

## Fetch step (run this through the PostHog MCP, then save the output to a file)

`execute-sql` returns a pipe-delimited text table (even with `call --json`, it comes back as
that text wrapped in a JSON string). Select only pipe-safe scalar columns — the free-text
`description` carries newlines/pipes that corrupt the table, so it's excluded here; the
one-line `hypothesis` is sanitized in SQL. Adjust the `INTERVAL` / `LIMIT` as needed:

    call --json execute-sql {"truncate": false, "query": "
      SELECT signal_ts, skill_name, severity, weight, confidence, finding_id,
             scout_run_id, task_run_id,
             replaceRegexpAll(coalesce(hypothesis,''), '[\\n\\r|]+', ' ') AS hypothesis
      FROM (
        SELECT document_id,
          argMax(metadata.source_product, inserted_at) AS source_product,
          argMax(metadata.deleted, inserted_at)        AS deleted,
          argMax(metadata.weight, inserted_at)         AS weight,
          argMax(metadata.extra.skill_name, inserted_at)   AS skill_name,
          argMax(metadata.extra.finding_id, inserted_at)   AS finding_id,
          argMax(metadata.extra.severity, inserted_at)     AS severity,
          argMax(metadata.extra.confidence, inserted_at)   AS confidence,
          argMax(metadata.extra.hypothesis, inserted_at)   AS hypothesis,
          argMax(metadata.extra.scout_run_id, inserted_at) AS scout_run_id,
          argMax(metadata.extra.task_run_id, inserted_at)  AS task_run_id,
          argMax(timestamp, inserted_at)               AS signal_ts
        FROM document_embeddings
        WHERE model_name = 'text-embedding-3-small-1536'
          AND product = 'signals' AND document_type = 'signal'
          AND timestamp >= now() - INTERVAL 30 DAY
        GROUP BY document_id
      )
      WHERE source_product = 'signals_scout' AND deleted != 'true'
      ORDER BY signal_ts DESC LIMIT 200"}

`model_name = 'text-embedding-3-small-1536'` is a REQUIRED equality filter (HogQL routes on
it). `deleted != 'true'` drops soft-deleted signals (the JSON field is a string). Attribution
(`skill_name`, `finding_id`, `severity`, `confidence`) lives in `metadata.extra`; only
`weight` and `source_id` are top-level. Reach this table through the `signals` /
`querying-posthog-data` skills if you want to extend the query.

## Format step

    python emitted_signals.py --signals emitted.txt [--now <ISO>] [--skill mcp-feedback,general]
                              [--severity P0,P1,P2] [--since <ISO>] [--sort weight] [--wide]

`--skill` takes a comma-separated set (the `signals-scout-` prefix is optional — `mcp-feedback`
matches `signals-scout-mcp-feedback`); substring match, so partials work. Output is plain text
(terminal-friendly); pipe to a `.txt` with `--out`.

Stdlib only. Python 3.11+."""

from __future__ import annotations

import re
import sys
import json
import argparse
from datetime import datetime, timezone

SKILL_PREFIX = "signals-scout-"

# the obligatory hedgehog
HEDGEHOG = r"""
         /////////,
       ///////////// .            PostHog · Signals
     ///////////////  `.            emitted signals
    ////////////////  o  `.
    `````````````````   `-.>
        '  '  '  '  '
"""

_FENCE = re.compile(r"```(?:\w+)?\n(.*?)```", re.DOTALL)


def parse_execute_sql(path: str) -> list[dict[str, str]]:
    """Parse the pipe-delimited table out of an `execute-sql` response.

    Handles both shapes the MCP produces: the `call --json` form (the whole response is a
    JSON string), and the overflow form (spilled to a file as raw text). The response wraps
    the real result in a fenced block after a "results table" marker, preceded by an example
    fenced block — so we take the LAST fenced block.
    """
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()

    text = raw.strip()
    if text.startswith(('"', "{", "[")):  # call --json wraps the text table in a JSON string
        try:
            decoded = json.loads(text)
            if isinstance(decoded, str):
                text = decoded
            elif isinstance(decoded, dict):
                for key in ("content", "text", "result", "results", "output"):
                    val = decoded.get(key)
                    if isinstance(val, str):
                        text = val
                        break
        except (json.JSONDecodeError, ValueError):
            pass  # not JSON after all — treat as raw text

    blocks = _FENCE.findall(text)
    block = blocks[-1].strip() if blocks else text.strip()

    lines = [ln for ln in block.splitlines() if ln.strip()]
    if not lines:
        return []
    header = [h.strip() for h in lines[0].split("|")]
    out: list[dict[str, str]] = []
    for ln in lines[1:]:
        cells = ln.split("|")
        if len(cells) != len(header):
            continue  # malformed / wrapped row — skip rather than misalign
        out.append({header[i]: cells[i].strip() for i in range(len(header))})
    return out


def parse_ts(ts: str | None) -> datetime | None:
    if not ts or ts == "None":
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Normalize to UTC-aware so a naive `--now` can't clash with offset-aware
    # signal timestamps in ago()/--since (the date sort dodges this via .timestamp()).
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def ago(dt: datetime | None, now: datetime | None) -> str:
    if not dt:
        return "?"
    if not now:
        return dt.strftime("%Y-%m-%d %H:%M")
    secs = int((now - dt).total_seconds())
    if secs < 0:
        return "future?"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def short(skill: str) -> str:
    return skill[len(SKILL_PREFIX):] if skill.startswith(SKILL_PREFIX) else skill


def num(s: str | None) -> str:
    """Trim a float string for display ('0.80' -> '0.8'); pass through non-numerics."""
    if not s or s == "None":
        return "-"
    try:
        return f"{float(s):g}"
    except ValueError:
        return s


def truncate(s: str, width: int) -> str:
    s = (s or "").strip()
    if s in ("", "None"):
        return ""
    return s if len(s) <= width else s[: width - 1] + "…"


def table(headers: list[str], body: list[list[str]]) -> list[str]:
    """Left-aligned fixed-width text table with a dashed header rule."""
    widths = [len(h) for h in headers]
    for r in body:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))

    def fmt(r: list[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)).rstrip()

    return [fmt(headers), "  ".join("-" * w for w in widths), *[fmt(r) for r in body]]


def matches_skill(skill: str, wanted: list[str]) -> bool:
    if not wanted:
        return True
    s = short(skill).lower()
    full = skill.lower()
    return any(short(w).lower() in s or w.lower() in full for w in wanted)


def render(
    signals: list[dict[str, str]],
    *,
    now: datetime | None,
    skills: list[str],
    severities: list[str],
    since: datetime | None,
    sort: str,
    wide: bool,
    why_width: int,
    art: bool,
) -> str:
    rows = []
    for s in signals:
        if not matches_skill(s.get("skill_name", ""), skills):
            continue
        sev = (s.get("severity") or "").strip()
        if severities and sev not in severities:
            continue
        dt = parse_ts(s.get("signal_ts"))
        if since and dt and dt < since:
            continue
        rows.append({**s, "_dt": dt})

    if sort == "weight":
        rows.sort(key=lambda r: float(r.get("weight") or 0), reverse=True)
    else:
        # sort on epoch seconds so a null timestamp can't trigger a tz-aware/naive clash
        rows.sort(key=lambda r: r["_dt"].timestamp() if r["_dt"] else float("-inf"), reverse=True)

    banner = [HEDGEHOG.strip("\n"), ""] if art else []

    if not rows:
        scope = f" matching {','.join(skills)}" if skills else ""
        return "\n".join([*banner,
                          "SIGNALS EMITTED BY SCOUTS", "",
                          f"No emitted scout signals{scope} in this window. Most runs close out "
                          "empty — that's the healthy default. If a run summary claims it emitted "
                          "but nothing is here, the emit was gated (dry-run at the time, AI "
                          "processing not approved, or source disabled) or failed."])

    # per-scout rollup
    per: dict[str, list[dict]] = {}
    for r in rows:
        per.setdefault(r.get("skill_name", "?"), []).append(r)

    L: list[str] = [*banner, "=" * 78, f" SIGNALS EMITTED BY SCOUTS   ({len(rows)} finding(s), {len(per)} scout(s))", "=" * 78, ""]

    roll: list[list[str]] = []
    for skill in sorted(per):
        items = per[skill]
        weights = [float(i.get("weight") or 0) for i in items]
        dts = [i["_dt"] for i in items if i["_dt"]]
        sevs = sorted({(i.get("severity") or "?").strip() for i in items})
        roll.append([
            short(skill),
            str(len(items)),
            ",".join(sevs),
            f"{min(weights):g}–{max(weights):g}" if weights else "-",
            ago(max(dts), now) if dts else "?",
        ])
    L += ["by scout:", ""]
    L += ["  " + ln for ln in table(["scout", "emits", "severities", "weight", "latest"], roll)]
    L += [""]

    # the finding-by-finding table
    headers = ["when", "scout", "sev", "wt", "conf", "finding_id", "why (hypothesis)"]
    if wide:
        headers = ["when", "scout", "sev", "wt", "conf", "run_id", "finding_id", "why (hypothesis)"]
    body: list[list[str]] = []
    for r in rows:
        base = [
            ago(r["_dt"], now),
            short(r.get("skill_name", "?")),
            (r.get("severity") or "-").strip() or "-",
            num(r.get("weight")),
            num(r.get("confidence")),
        ]
        run_col = [r.get("scout_run_id", "-")] if wide else []
        body.append([*base, *run_col, r.get("finding_id", "-"), truncate(r.get("hypothesis", ""), why_width)])
    L += table(headers, body)

    L += ["", "-" * 78, " notes", "-" * 78,
          " what     each row is one signal that CLEARED every emit gate and persisted — the",
          "          authoritative 'actually emitted' record (not the run summary's prose claim).",
          " sev      P0-P4, scout-assigned, informational only (no routing).",
          " wt/conf  weight = how much attention it deserves; confidence = how sure the scout is",
          "          it's real (emit gate is conf >= 0.65). Both scout-set on the signal.",
          " run_id   the scout_run_id (--wide) — pass to signals-scout-runs-retrieve, or to",
          "          render_run_report.py, to see the full run that emitted it.",
          " missing  a finding a run summary claims but that is ABSENT here was gated (dry-run at",
          "          emit time / AI processing not approved / source disabled) or failed."]
    return "\n".join(L)


def split_csv(val: str | None) -> list[str]:
    return [p.strip() for p in val.split(",") if p.strip()] if val else []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--signals", required=True, help="execute-sql output file (the emitted-signals query)")
    ap.add_argument("--now", help="ISO-8601 current time for 'ago' columns")
    ap.add_argument("--skill", help="comma-separated scout set to filter to (prefix optional)")
    ap.add_argument("--severity", help="comma-separated severities to keep (e.g. P0,P1,P2)")
    ap.add_argument("--since", help="ISO-8601 lower bound on emit time (client-side filter)")
    ap.add_argument("--sort", choices=["date", "weight"], default="date", help="sort order (default: date)")
    ap.add_argument("--wide", action="store_true", help="add the scout_run_id column")
    ap.add_argument("--why-width", type=int, default=72, help="truncation width for the hypothesis column")
    ap.add_argument("--no-art", dest="art", action="store_false", help="skip the hedgehog banner")
    ap.add_argument("--out", help="write here instead of stdout (use a .txt path)")
    args = ap.parse_args()

    signals = parse_execute_sql(args.signals)
    report = render(
        signals,
        now=parse_ts(args.now) if args.now else None,
        skills=split_csv(args.skill),
        severities=split_csv(args.severity),
        since=parse_ts(args.since) if args.since else None,
        sort=args.sort,
        wide=args.wide,
        why_width=args.why_width,
        art=args.art,
    )
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
