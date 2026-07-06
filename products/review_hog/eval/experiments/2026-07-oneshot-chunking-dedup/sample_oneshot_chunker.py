"""Sample the one-shot chunker's chunk plans offline (no pipeline runs) — the cheap de-noiser for
the 2026-07-oneshot-chunking-dedup experiment's chunk-structure read (2-vs-3-chunk coin flip).

Requires a persisted `pr_snapshot` for the latest team-1 ReviewReport, so run it while a run's data
is still in the DB (after its dump, BEFORE `reset_review_hog`). Each sample is one direct gateway
call (~cents, no sandbox), sequential.

    N_SAMPLES=5 OUT_FILE=products/review_hog/eval/experiments/2026-07-oneshot-chunking-dedup/runs/chunker-offline-sample.md \
        python manage.py shell -c "exec(open('products/review_hog/eval/experiments/2026-07-oneshot-chunking-dedup/sample_oneshot_chunker.py').read())"

Gotcha: a PostHog Code desktop-harness shell overrides LLM_GATEWAY_URL to the app's own proxy —
prefix the command with LLM_GATEWAY_URL=http://localhost:3308 when driving this from an agent shell.
"""

import os
import asyncio
from pathlib import Path

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import PRSnapshotArtefact, parse_artefact_content
from products.review_hog.backend.reviewer.constants import (
    CHUNKING_ONESHOT_MAX_ADDITIONS,
    ONESHOT_MODEL,
    ONESHOT_REASONING_EFFORT,
    SINGLE_CHUNK_GATE_ADDITIONS,
)
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.sandbox.direct_llm import run_oneshot_review
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import (
    CHUNKING_SYSTEM_PROMPT,
    count_reviewable_additions,
    generate_chunking_prompt,
)

TEAM = 1
N_SAMPLES = int(os.environ.get("N_SAMPLES", "5"))
OUT_FILE = os.environ.get(
    "OUT_FILE", "products/review_hog/eval/experiments/2026-07-oneshot-chunking-dedup/runs/chunker-offline-sample.md"
)

report = ReviewReport.objects.for_team(TEAM).order_by("-created_at").first()
if report is None:
    raise SystemExit("No ReviewReport for team 1 — run (or at least fetch) a review first.")

snapshot: PRSnapshotArtefact | None = None
for a in ReviewReportArtefact.objects.for_team(TEAM).filter(
    report_id=report.id, type=ReviewReportArtefact.ArtefactType.PR_SNAPSHOT
):
    c = parse_artefact_content(a.type, a.content)
    if isinstance(c, PRSnapshotArtefact):
        snapshot = c  # latest wins, like the dump script
if snapshot is None:
    raise SystemExit("No pr_snapshot artefact — did reset_review_hog already wipe the run?")

additions = count_reviewable_additions(snapshot.pr_files)
file_additions = {f.filename: f.additions for f in snapshot.pr_files}
if additions <= SINGLE_CHUNK_GATE_ADDITIONS:
    print(  # noqa: T201 — eval script, stdout is the intended output channel
        f"WARNING: {additions} reviewable additions <= single-chunk gate — prod would never call the chunker here."
    )
if additions > CHUNKING_ONESHOT_MAX_ADDITIONS:
    print(  # noqa: T201 — eval script, stdout is the intended output channel
        f"WARNING: {additions} reviewable additions > one-shot gate — prod would take the sandbox path here."
    )

prompt = generate_chunking_prompt(snapshot.pr_metadata, snapshot.pr_comments, snapshot.pr_files)


async def _samples() -> list[ChunksList]:
    plans: list[ChunksList] = []
    for i in range(N_SAMPLES):
        plan = await run_oneshot_review(
            team_id=TEAM,
            user_id=1,
            prompt=prompt,
            system_prompt=CHUNKING_SYSTEM_PROMPT,
            model_to_validate=ChunksList,
            step_name="chunking-offline-sample",
        )
        sizes = [sum(file_additions.get(f.filename, 0) for f in ch.files) for ch in plan.chunks]
        print(  # noqa: T201 — eval script, stdout is the intended output channel
            f"sample {i + 1}/{N_SAMPLES}: {len(plan.chunks)} chunk(s), additions per chunk = {sizes}"
        )
        plans.append(plan)
    return plans


plans = asyncio.run(_samples())

lines = [
    "# One-shot chunker — offline chunk-plan sample",
    "",
    f"PR #{snapshot.pr_metadata.number} @ `{snapshot.head_sha}` · {additions} reviewable additions · "
    f"{len(snapshot.pr_files)} reviewable files · model `{ONESHOT_MODEL}` @ {ONESHOT_REASONING_EFFORT} · "
    f"{N_SAMPLES} samples",
    "",
]
reviewable = {f.filename for f in snapshot.pr_files}
for i, plan in enumerate(plans, start=1):
    assigned = [f.filename for ch in plan.chunks for f in ch.files]
    coverage_note = ""
    missing = reviewable - set(assigned)
    extra = set(assigned) - reviewable
    if missing or extra or len(assigned) != len(set(assigned)):
        coverage_note = f" · **COVERAGE VIOLATION** missing={sorted(missing)} extra={sorted(extra)}"
    lines.append(f"## Sample {i} — {len(plan.chunks)} chunk(s){coverage_note}")
    for ch in plan.chunks:
        size = sum(file_additions.get(f.filename, 0) for f in ch.files)
        lines.append(
            f"- chunk {ch.chunk_id} ({ch.chunk_type or '—'}, ~{size} adds): {', '.join(f.filename for f in ch.files)}"
        )
    lines.append("")

out_path = Path(OUT_FILE)
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text("\n".join(lines))
print(f"Wrote {out_path} ({len(plans)} samples)")  # noqa: T201 — eval script, stdout is the intended output channel
