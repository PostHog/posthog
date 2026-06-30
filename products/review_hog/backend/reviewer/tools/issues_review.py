import json

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk
from products.review_hog.backend.reviewer.tools.prompt_helpers import (
    build_chunk_prompt_context,
    load_template_and_schema,
)


def _covered_findings_for_chunk(prior_findings: list[ReviewIssueFinding], chunk: Chunk) -> str | None:
    """The already-covered findings on this chunk's files, as compact JSON — or None if there are none.

    Only file/lines/title/problem are surfaced (not our suggestion): the agent needs to recognize the
    problem as already raised, not re-derive our fix.
    """
    chunk_files = {f.filename for f in chunk.files}
    covered = [
        {
            "file": f.file,
            "lines": [lr.model_dump(mode="json") for lr in f.lines],
            "title": f.title,
            "problem": f.body,
        }
        for f in prior_findings
        if f.file in chunk_files
    ]
    return json.dumps(covered, indent=2) if covered else None


REVIEW_SYSTEM_PROMPT = (
    "You are a senior code reviewer focused on identifying and documenting issues in a GitHub PR chunk.\n"
    "Focus on:\n"
    "- Identifying real issues that impact code quality, security, or performance\n"
    "- Providing specific, actionable suggestions for each issue\n"
    "- Categorizing issues by priority (must_fix, should_fix, consider)\n"
    "- Following the specific output format requirements for IssuesReview\n"
    "IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."
)


def build_review_prompt(
    *,
    skill_name: str,
    skill_version: int,
    chunk: Chunk,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    prior_findings: list[ReviewIssueFinding],
) -> str:
    """Render one (perspective, chunk) review prompt.

    Each (perspective × chunk) review is independent — no cross-perspective context; overlap between
    perspectives is resolved downstream by deduplication. The reviewer reconstructs the chunk's intent
    itself from the diff + `<pr_intent>` (its mandated investigation step), so no separate analysis
    pass is fed in. The perspective's focus isn't spliced in — the prompt instructs the agent to
    `skill-get` it over MCP — so we pass the perspective's skill name and pinned version, not its body.
    `prior_findings` are problems earlier turns already found on this chunk's files; surfacing them
    tells the agent not to re-investigate already-covered ground.
    """
    main_template, output_schema = load_template_and_schema("issues_review")
    return main_template.render(
        **build_chunk_prompt_context(chunk, pr_metadata, pr_comments, pr_files),
        COVERED_FINDINGS=_covered_findings_for_chunk(prior_findings, chunk),
        OUTPUT_SCHEMA=output_schema,
        PERSPECTIVE_SKILL_NAME=skill_name,
        PERSPECTIVE_SKILL_VERSION=skill_version,
    )
