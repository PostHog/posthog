"""Render flakes.json into a deterministic Slack message (main + thread reply). No prose generation."""

import os
import re
import json
import subprocess
from pathlib import Path

DATA = Path(os.environ.get("FLAKES_DATA", "."))
REPO = Path(
    subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
)
data = json.loads((DATA / "flakes.json").read_text())

totals = data["totals"]
tests = data["tests"]
window = data["window"]

confirmed = sorted(
    (t for t in tests if t["classification"] == "confirmed"),
    key=lambda t: (-t["runs_recovered"], -t["failures"]),
)
runs_rescued = sum(t["runs_recovered"] for t in tests)

TEAM_LABELS = {"UNOWNED": "unowned", "unresolved": "moved/deleted"}

# Channel name comes from the owners registry (hogli owners:who); ID resolved once via Slack API.
TEAM_CHANNELS = {
    "team-warehouse-sources": ("#team-warehouse-sources", "C0A6L24BU0P"),
    "batch-exports": ("#team-batch-exports", "C082R7YJAMR"),
}


def owner_cell(team: str) -> str:
    if team in TEAM_CHANNELS:
        name, channel_id = TEAM_CHANNELS[team]
        # Display without the "team-" prefix to keep the column narrow; link goes to the full channel.
        return f"[#{name.removeprefix('#team-')}](https://posthog.slack.com/archives/{channel_id})"
    return TEAM_LABELS.get(team, team)


def test_source_url(t: dict) -> str | None:
    if not t.get("file"):
        return None
    url = f"https://github.com/PostHog/posthog/blob/master/{t['file']}"
    fn = re.sub(r"\[.*\]$", "", t["test_id"].split("::")[-1])
    try:
        for i, line in enumerate((REPO / t["file"]).read_text().splitlines(), 1):
            if re.search(rf"def {re.escape(fn)}\b", line):
                return f"{url}#L{i}"
    except OSError:
        pass
    return url


def evidence_links(t: dict) -> str:
    pairs = t.get("evidence") or [{"run_id": t["sample_run_id"], "job_id": None}]
    links = []
    for i, p in enumerate(pairs, 1):
        url = f"https://github.com/PostHog/posthog/actions/runs/{p['run_id']}"
        if p.get("job_id"):
            url += f"/job/{p['job_id']}"
        links.append(f"[{i}]({url})")
    return " ".join(links)


def row(t: dict) -> str:
    name = t["test_id"].split("::")[-1]
    if len(name) > 36:
        name = name[:35] + "…"
    src = test_source_url(t)
    test_cell = f"[{name}]({src})" if src else name
    return f"| {test_cell} | {owner_cell(t['team'])} | {t['runs_recovered']} | {t['failures']} | {evidence_links(t)} |"


top = confirmed[:10]
table = "\n".join(
    [
        "| test | owner | rescued | fails | logs |",
        "|---|---|---|---|---|",
        *[row(t) for t in top],
    ]
)

# Footer: rendered as a blockquote here; the production Block Kit message uses a `context` block
# (small muted text) for the same lines. Two short lines wrap better in the narrow thread sidebar
# than one long sentence.
window_label = f"Jul {window['from'][8:].lstrip('0')}-{window['to'][8:].lstrip('0')}"
main = f"""**Top {len(top)} flaky tests this week** · {window_label} · backend CI

{table}

> Fix: `/fixing-flaky-tests`
> Park 14 days: `hogli test:quarantine add <test id>`"""

thread = f"""**This week in numbers**

| | |
|---|---|
| jobs rerun (attempt 2+) | {totals["rerun_jobs"]:,} (${totals["rerun_cost_usd"]:,.0f}) |
| tests that failed | {totals["unique_failing_tests"]} |
| failed, then passed on rerun | {len(confirmed)} |
| runs saved by a rerun | {runs_rescued} |
| fixed vs last week | n/a (first run) |"""

(DATA / "slack_message.txt").write_text(main + "\n\n===THREAD REPLY===\n\n" + thread)
print(main)  # noqa: T201
print("\n===THREAD REPLY===\n")  # noqa: T201
print(thread)  # noqa: T201
