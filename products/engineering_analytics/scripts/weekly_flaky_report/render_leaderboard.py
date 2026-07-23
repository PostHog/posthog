"""Render flakes.json into a self-contained leaderboard HTML page."""

import os
import html
import json
from pathlib import Path

DATA = Path(os.environ.get("FLAKES_DATA", "."))
data = json.loads((DATA / "flakes.json").read_text())

teams = data["teams"]
tests = data["tests"]
clusters = data["clusters"]
totals = data["totals"]

confirmed = sorted(
    (t for t in tests if t["classification"] == "confirmed"),
    key=lambda t: (-t["rerun_recovered_failures"], -t["failures"]),
)
suspected = sorted(
    (t for t in tests if t["classification"] == "suspected"),
    key=lambda t: (-t["branches"], -t["failures"]),
)
bursts = sorted(
    (t for t in tests if t["classification"] == "master_burst"),
    key=lambda t: -t["failures"],
)[:5]
runs_rescued = sum(t["runs_recovered"] for t in tests)

TEAM_LABELS = {"UNOWNED": "Unowned (posthog/ and ee/ core)", "unresolved": "Moved or deleted since"}


def team_label(slug: str) -> str:
    return TEAM_LABELS.get(slug, slug)


def short_test(tid: str) -> str:
    parts = tid.split("::")
    return html.escape(parts[-1]) + '<span class="path">' + html.escape(parts[0]) + "</span>"


def run_link(run_id: int) -> str:
    return f'<a href="https://github.com/PostHog/posthog/actions/runs/{run_id}" target="_blank">example run</a>'


def evidence_links(t: dict) -> str:
    pairs = t.get("evidence")
    if not pairs:
        return run_link(t["sample_run_id"])
    links = []
    for i, p in enumerate(pairs, 1):
        url = f"https://github.com/PostHog/posthog/actions/runs/{p['run_id']}"
        if p.get("job_id"):
            url += f"/job/{p['job_id']}"
        links.append(f'<a href="{url}" target="_blank">job {i}</a>')
    return " · ".join(links)


ranked = sorted(teams.items(), key=lambda kv: -kv[1]["failures"])
max_failures = max(agg["failures"] for _, agg in ranked)

team_rows = []
for slug, agg in ranked:
    bar_pct = round(agg["failures"] / max_failures * 100, 1)
    team_rows.append(f"""
      <tr>
        <td class="team">{html.escape(team_label(slug))}</td>
        <td class="num">{agg["confirmed"]}</td>
        <td class="num">{agg["suspected"]}</td>
        <td class="num">{agg["clusters"]}</td>
        <td class="num">{agg["runs_recovered"]}</td>
        <td class="barcell"><div class="bar" style="width:{bar_pct}%"></div><span class="barlabel">{agg["failures"]:,}</span></td>
      </tr>""")

confirmed_rows = []
for t in confirmed:
    confirmed_rows.append(f"""
      <tr>
        <td class="test">{short_test(t["test_id"])}</td>
        <td class="team">{html.escape(team_label(t["team"]))}</td>
        <td class="num">{t["rerun_recovered_failures"]}</td>
        <td class="num">{t["runs_recovered"]}</td>
        <td class="num">{t["failures"]}</td>
        <td class="num">{t["branches"]}</td>
        <td>{evidence_links(t)}</td>
      </tr>""")

suspected_rows = []
for t in suspected:
    suspected_rows.append(f"""
      <tr>
        <td class="test">{short_test(t["test_id"])}</td>
        <td class="team">{html.escape(team_label(t["team"]))}</td>
        <td class="num">{t["failures"]}</td>
        <td class="num">{t["branches"]}</td>
        <td class="num">{t["master_failures"]}</td>
        <td>{evidence_links(t)}</td>
      </tr>""")

cluster_rows = []
for c in sorted(clusters, key=lambda c: -c["failures"]):
    fname = c["file"] or "files moved or deleted since the failures"
    cluster_rows.append(f"""
      <tr>
        <td class="test">{html.escape(fname)}</td>
        <td class="team">{html.escape(team_label(c["team"]))}</td>
        <td class="num">{c["tests"]}</td>
        <td class="num">{c["failures"]}</td>
        <td>{run_link(c["sample_run_id"])}</td>
      </tr>""")

burst_items = "".join(
    f"<li><code>{html.escape(t['test_id'].split('::')[-1])}</code> ({t['failures']} failures, {t['master_failures']} on master)</li>"
    for t in bursts[:3]
)

page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Last week's flakes</title>
<style>
:root {{
  color-scheme: light;
  --surface-1: #fcfcfb; --page: #f9f9f7;
  --ink-1: #0b0b0b; --ink-2: #52514e; --ink-muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --ring: rgba(11,11,11,0.10);
  --bar: #2a78d6; --bar-soft: #cde2fb;
  --status-critical: #d03b3b; --status-warning: #fab219; --status-good: #0ca30c; --status-serious: #ec835a;
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    color-scheme: dark;
    --surface-1: #1a1a19; --page: #0d0d0d;
    --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10);
    --bar: #3987e5; --bar-soft: #184f95;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --surface-1: #1a1a19; --page: #0d0d0d;
  --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10);
  --bar: #3987e5; --bar-soft: #184f95;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--page); color: var(--ink-1);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1080px; margin: 0 auto; padding: 32px 20px 64px; }}
h1 {{ font-size: 28px; margin: 0 0 4px; }}
h2 {{ font-size: 19px; margin: 40px 0 4px; }}
.sub {{ color: var(--ink-2); margin: 0 0 12px; }}
.note {{ color: var(--ink-muted); font-size: 13px; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 24px 0; }}
.tile {{ background: var(--surface-1); border: 1px solid var(--ring); border-radius: 10px; padding: 14px 16px; }}
.tile .v {{ font-size: 26px; font-weight: 650; }}
.tile .k {{ color: var(--ink-2); font-size: 13px; }}
.card {{ background: var(--surface-1); border: 1px solid var(--ring); border-radius: 10px; padding: 6px 16px 14px; overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; }}
th {{ text-align: left; color: var(--ink-muted); font-size: 12px; font-weight: 500; text-transform: uppercase;
  letter-spacing: 0.04em; border-bottom: 1px solid var(--axis); padding: 10px 10px 6px; white-space: nowrap; }}
td {{ border-bottom: 1px solid var(--grid); padding: 8px 10px; vertical-align: top; }}
tr:last-child td {{ border-bottom: none; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
td.rank {{ color: var(--ink-muted); font-variant-numeric: tabular-nums; }}
td.team {{ white-space: nowrap; }}
td.test {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; max-width: 420px; overflow-wrap: anywhere; }}
td.test .path {{ display: block; color: var(--ink-muted); font-size: 11px; }}
td.barcell {{ min-width: 220px; position: relative; white-space: nowrap; }}
.bar {{ background: var(--bar); border-radius: 0 4px 4px 0; height: 14px; display: inline-block; vertical-align: middle; min-width: 2px; }}
.barlabel {{ margin-left: 8px; font-variant-numeric: tabular-nums; color: var(--ink-2); font-size: 13px; }}
a {{ color: var(--bar); }}
.badge {{ display: inline-block; border-radius: 5px; padding: 1px 7px; font-size: 12px; font-weight: 600; }}
.badge.crit {{ background: color-mix(in srgb, var(--status-critical) 14%, transparent); color: var(--status-critical); }}
.badge.warn {{ background: color-mix(in srgb, var(--status-warning) 18%, transparent); color: var(--ink-1); }}
.golden {{ border-left: 4px solid var(--status-warning); }}
.golden .v {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 15px; overflow-wrap: anywhere; }}
code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; }}
ul {{ margin: 6px 0; padding-left: 20px; }}
.method p, .method li {{ color: var(--ink-2); font-size: 14px; }}
</style>
</head>
<body>
<main>
<h1>Last week's flakes</h1>
<p class="sub">Flaky test leaderboard for PostHog/posthog, {data["window"]["from"]} to {data["window"]["to"]}. Backend CI (pytest) only. Built from CI logs, test spans, GitHub runs and code ownership. Prototype, local only.</p>

<div class="tiles">
  <div class="tile"><div class="v">${totals["rerun_cost_usd"]:,.0f}</div><div class="k">spent on rerun jobs this week ({totals["rerun_jobs"]:,} jobs at attempt 2+)</div></div>
  <div class="tile"><div class="v">{totals["unique_failing_tests"]}</div><div class="k">distinct tests failed in CI ({totals["failure_rows"]:,} failure events)</div></div>
  <div class="tile"><div class="v">{len(confirmed)}</div><div class="k">confirmed flaky tests (failed, then passed on rerun)</div></div>
  <div class="tile"><div class="v">{runs_rescued}</div><div class="k">runs rescued by someone pressing rerun</div></div>
</div>

<h2>Flakes by owning team</h2>
<p class="sub">Grouped by owner so each team can find theirs and route the work. This is routing, not a ranking.</p>
<div class="card">
<table>
<thead><tr><th>Team</th><th class="num">Confirmed</th><th class="num">Suspected</th><th class="num">Clusters</th><th class="num">Runs rescued</th><th>Failure events</th></tr></thead>
<tbody>{"".join(team_rows)}
</tbody>
</table>
</div>

<h2><span class="badge crit">confirmed</span> Flaky tests with rerun proof</h2>
<p class="sub">Each of these failed and then passed on a rerun of the same code. That is a flake, not a broken test.</p>
<div class="card">
<table>
<thead><tr><th>Test</th><th>Team</th><th class="num">Rerun-rescued fails</th><th class="num">Runs rescued</th><th class="num">Failures</th><th class="num">Branches</th><th>Evidence</th></tr></thead>
<tbody>{"".join(confirmed_rows)}
</tbody>
</table>
</div>

<h2><span class="badge warn">suspected</span> Failing across many unrelated branches</h2>
<p class="sub">No rerun proof yet, but each failed on 3+ unrelated branches in one week. Unrelated PRs rarely break the same test.</p>
<div class="card">
<table>
<thead><tr><th>Test</th><th>Team</th><th class="num">Failures</th><th class="num">Branches</th><th class="num">On master</th><th>Evidence</th></tr></thead>
<tbody>{"".join(suspected_rows)}
</tbody>
</table>
</div>

<h2>Co-failing clusters</h2>
<p class="sub">Five or more tests in one file failing together. Usually one shared fixture or infra issue, so they count as one problem, not dozens.</p>
<div class="card">
<table>
<thead><tr><th>File</th><th>Team</th><th class="num">Tests</th><th class="num">Failures</th><th>Evidence</th></tr></thead>
<tbody>{"".join(cluster_rows)}
</tbody>
</table>
</div>

<div class="method">
<h2>Excluded: broken on master, not flaky</h2>
<p>{len(bursts)} of the top offenders were master breakage bursts (one bad merge, fixed or reverted), not flakes. They are excluded from the leaderboard. Examples:</p>
<ul>{burst_items}</ul>

<h2>The ownership gap</h2>
<p>The number one team on this leaderboard is nobody. {sum(1 for t in confirmed + suspected if t["team"] == "UNOWNED")} of the {len(confirmed) + len(suspected)} confirmed and suspected flakes live in <code>posthog/</code> or <code>ee/</code> paths with no <code>owners.yaml</code>. 1,583 of 6,441 test files in the repo resolve to no owner. Attribution here runs the canonical <code>owners.yaml</code> resolver locally, so these are genuine coverage gaps, not tooling gaps. (The CI span emitter uses the same resolver at capture time, but stamping only shipped Jul 17, so span-based views also undercount owners for older windows.) Adding <code>owners.yaml</code> to the core dirs above is the single highest-leverage step for this leaderboard to work.</p>

<h2>Method and sources</h2>
<ul>
<li><b>Failure events:</b> <code>engineering_analytics_ci_failures</code> (DevEx project 347861), a view over CI logs matching pytest <code>FAILED path::test</code> lines. Window: 7 days.</li>
<li><b>Rerun proof:</b> a failure at attempt N of a run whose final attempt succeeded (join against <code>github_workflow_runs</code>), plus span-level <code>rerun_passed</code> outcomes from <code>posthog.trace_spans</code> (service <code>ci-backend</code>).</li>
<li><b>Cost:</b> <code>engineering_analytics_job_costs</code>, sum of <code>estimated_cost_usd</code> for jobs at attempt 2+.</li>
<li><b>Ownership:</b> test file resolved per test id, then <code>hogli owners:resolve</code> (nearest <code>owners.yaml</code> wins). Relative product paths matched by suffix with the CI job name as tiebreaker.</li>
<li><b>Classification:</b> confirmed = rerun proof; suspected = failed on 3+ branches; cluster = 5+ suspected tests in one file; master burst = over half the failures on master across at most 3 branches (excluded).</li>
<li><b>Known gaps:</b> pytest only (no jest, playwright, rust); rerun proof requires someone actually rerunning; quarantine list (<code>.test_quarantine.json</code>) is currently empty, so nothing on this page is protected.</li>
</ul>
</div>

</main>
</body>
</html>
"""

(DATA / "leaderboard.html").write_text(page)
print("wrote leaderboard.html,", len(page), "chars; runs_rescued =", runs_rescued)  # noqa: T201
