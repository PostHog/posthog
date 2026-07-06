"""Sample the one-shot chunker against the LOCAL #62096 fixtures — no GitHub, no DB state needed.

Fixture-based variant of `sample_oneshot_chunker.py` for prompt iteration: parses the topology round's
frozen `pr62096.diff` into `PRFile`s (same test/lockfile filters and patch parser as the real fetch),
renders the current chunking prompt, and fires N direct gateway calls.

    N_SAMPLES=5 python manage.py shell -c "exec(open('products/review_hog/eval/experiments/2026-07-oneshot-chunking-dedup/sample_oneshot_chunker_fixture.py').read())"

Known deviation from the real runs: PR body is not in the fixtures, so PR_INTENT carries the title only —
irrelevant for split-structure checks. Prefix with LLM_GATEWAY_URL=http://localhost:3308 in agent shells.
"""

import os
import json
import asyncio
from pathlib import Path

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.sandbox.direct_llm import run_oneshot_review
from products.review_hog.backend.reviewer.tools.github_meta import PRFilter, PRParser
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import (
    CHUNKING_SYSTEM_PROMPT,
    count_reviewable_additions,
    generate_chunking_prompt,
)

N_SAMPLES = int(os.environ.get("N_SAMPLES", "5"))
_FIXTURES = Path("products/review_hog/eval/experiments/2026-07-reviewer-topology/fixtures")


def _files_from_diff(diff_text: str) -> list[PRFile]:
    # Fixture format (the pipeline's snapshot diff): filename at column 0, that file's unified patch
    # lines below it indented by two spaces.
    files: list[PRFile] = []
    current: str | None = None
    patch_lines: list[str] = []

    def _flush() -> None:
        nonlocal current, patch_lines
        if current is not None and not (PRFilter.is_test_file(current) or PRFilter.is_filtered_file(current)):
            additions = sum(1 for line in patch_lines if line.startswith("+") and not line.startswith("+++"))
            deletions = sum(1 for line in patch_lines if line.startswith("-") and not line.startswith("---"))
            files.append(
                PRFile(
                    filename=current,
                    status="modified",
                    additions=additions,
                    deletions=deletions,
                    changes=PRParser.parse_patch("\n".join(patch_lines)),
                )
            )
        current, patch_lines = None, []

    for line in diff_text.split("\n"):
        if line and not line[0].isspace():
            _flush()
            current = line.strip()
        elif current is not None:
            patch_lines.append(line[2:] if line.startswith("  ") else line)
    _flush()
    return files


pr_files = _files_from_diff((_FIXTURES / "pr62096.diff").read_text())


def _comment(line: str) -> PRComment:
    raw = json.loads(line)
    raw.setdefault("diff_hunk", "")
    raw.setdefault("created_at", "2025-05-01T00:00:00Z")
    return PRComment.model_validate(raw)


pr_comments = [
    _comment(line) for line in (_FIXTURES / "pr62096_prior_comments.jsonl").read_text().splitlines() if line.strip()
]
pr_metadata = PRMetadata(
    number=62096,
    title="feat(ph AI): add action CRUD tools to ph AI",
    state="open",
    draft=False,
    created_at="2025-05-01T00:00:00Z",
    updated_at="2025-05-01T00:00:00Z",
    author="posthog-dev",
    base_branch="master",
    head_branch="feat/action-crud-tools",
    commits=1,
    additions=674,
    deletions=1,
    changed_files=10,
)

file_additions = {f.filename: f.additions for f in pr_files}
reviewable = {f.filename for f in pr_files}
print(  # noqa: T201 — eval script, stdout is the intended output channel
    f"FIXTURE total reviewable adds: {count_reviewable_additions(pr_files)} files: {len(pr_files)}"
)
prompt = generate_chunking_prompt(pr_metadata, pr_comments, pr_files)


async def _samples() -> None:
    for i in range(N_SAMPLES):
        plan = await run_oneshot_review(
            team_id=1,
            user_id=1,
            prompt=prompt,
            system_prompt=CHUNKING_SYSTEM_PROMPT,
            model_to_validate=ChunksList,
            step_name="chunking-tuned-sample",
        )
        sizes = [sum(file_additions.get(f.filename, 0) for f in ch.files) for ch in plan.chunks]
        assigned = [f.filename for ch in plan.chunks for f in ch.files]
        cov = "OK" if set(assigned) == reviewable and len(assigned) == len(set(assigned)) else "VIOLATION"
        print(  # noqa: T201 — eval script, stdout is the intended output channel
            f"TUNED sample {i + 1}/{N_SAMPLES}: {len(plan.chunks)} chunks, sizes={sizes}, coverage={cov}"
        )


asyncio.run(_samples())
