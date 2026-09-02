"""Dump one PR's resolution-stage state to a per-phase `.md` for the resolution e2e experiment.

Run via manage.py shell so Django is configured (mirrors dump_result.py):

    LABEL=P1-chained PR_NUMBER=72074 TEAM_ID=1 \
        OUT_DIR=products/review_hog/eval/experiments/2026-07-resolution-e2e/runs \
        python manage.py shell -c "exec(open('products/review_hog/eval/scripts/dump_resolution.py').read())"

Reads the PR's `ReviewReport` and writes `<OUT_DIR>/<LABEL>.md` with: the per-thread verdict table
(latest-wins, straight from `load_thread_verdicts`), the outcome/delivery tallies, and the raw
resolution artefact trail (`task_run` / `commit` / `note` rows, newest last). Read-only and
defensive — written for the experiment, exercised for the first time during it; fix forward.
The live-GitHub thread table and `gh pr checks` output are appended to the file by hand (the
dump is DB truth; SC9 is the comparison between the two).
"""

import os
from datetime import UTC, datetime

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.persistence import load_thread_verdicts

LABEL = os.environ.get("LABEL", "unlabeled")
PR_NUMBER = int(os.environ.get("PR_NUMBER", "72074"))
TEAM_ID = int(os.environ.get("TEAM_ID", "1"))
OUT_DIR = os.environ.get("OUT_DIR", "products/review_hog/eval/experiments/2026-07-resolution-e2e/runs")

report = (
    ReviewReport.objects.for_team(TEAM_ID)
    .filter(pr_number=PR_NUMBER, repository__iexact="posthog/posthog")
    .order_by("-created_at")
    .first()
)
if report is None:
    raise SystemExit(f"No ReviewReport for posthog/posthog#{PR_NUMBER} on team {TEAM_ID} — has any run executed?")

verdicts = load_thread_verdicts(team_id=TEAM_ID, report_id=str(report.id))

lines: list[str] = [
    f"# {LABEL} — resolution dump · posthog/posthog#{PR_NUMBER}",
    "",
    f"- dumped: {datetime.now(UTC).isoformat(timespec='seconds')}",
    f"- report: `{report.id}` · run_count {report.run_count} · published_head `{report.published_head_sha or '—'}`",
    f"- verdicts (latest per thread): **{len(verdicts)}**",
    "",
    "## Per-thread verdicts",
    "",
    "| thread | outcome | author | bot | reply_posted | resolved | commit | watermark | reasoning (head) |",
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
]
tally: dict[str, int] = {}
replied = resolved = 0
for thread_id in sorted(verdicts):
    v = verdicts[thread_id]
    tally[v.outcome] = tally.get(v.outcome, 0) + 1
    replied += int(v.reply_posted)
    resolved += int(v.resolved)
    reasoning = " ".join((v.reasoning or "").split())[:110]
    lines.append(
        f"| `{thread_id}` | {v.outcome} | {v.author_login or '—'} | {'y' if v.author_is_bot else 'n'} "
        f"| {'y' if v.reply_posted else 'n'} | {'y' if v.resolved else 'n'} "
        f"| {v.commit_sha[:10] if v.commit_sha else '—'} | {v.latest_comment_id or '—'} | {reasoning} |"
    )

lines += [
    "",
    "## Tallies",
    "",
    f"- outcomes: {tally or '—'}",
    f"- replies delivered: {replied}/{len(verdicts)} · resolves delivered: {resolved}/{len(verdicts)}",
    "",
    "## Artefact trail (task_run / commit / note, oldest first)",
    "",
]
trail = (
    ReviewReportArtefact.objects.for_team(TEAM_ID)
    .filter(report_id=report.id, type__in=["task_run", "commit", "note"])
    .order_by("created_at")
)
for row in trail:
    content = " ".join(str(row.content or "").split())[:220]
    lines.append(f"- `{row.created_at:%H:%M:%S}` **{row.type}** {content}")
if not trail:
    lines.append("- (none)")

lines += ["", "## Live GitHub state + CI (paste by hand)", "", "_(gh graphql thread table + `gh pr checks 72074`)_", ""]

os.makedirs(OUT_DIR, exist_ok=True)
out_path = os.path.join(OUT_DIR, f"{LABEL}.md")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(  # noqa: T201 — eval script, stdout is the intended output channel
    f"wrote {out_path} · {len(verdicts)} verdict(s) · outcomes {tally}"
)
