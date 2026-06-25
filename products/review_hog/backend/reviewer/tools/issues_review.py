import json
import asyncio
import logging

from asgiref.sync import sync_to_async
from jinja2 import Template

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import IssuesReview
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList
from products.review_hog.backend.reviewer.persistence import load_perspective_results, persist_perspective_results
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review
from products.review_hog.backend.reviewer.skill_loader import LoadedPerspective, load_perspectives_for_run
from products.review_hog.backend.reviewer.tools.prompt_helpers import (
    build_chunk_prompt_context,
    load_template_and_schema,
)

# Configure logging
logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a senior code reviewer focused on identifying and documenting issues in a GitHub PR chunk.\n"
    "Focus on:\n"
    "- Identifying real issues that impact code quality, security, or performance\n"
    "- Providing specific, actionable suggestions for each issue\n"
    "- Categorizing issues by priority (must_fix, should_fix, consider)\n"
    "- Following the specific output format requirements for IssuesReview\n"
    "IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."
)


async def review_chunks(
    *,
    team_id: int,
    report_id: str,
    head_sha: str,
    chunks_data: ChunksList,
    analyses: dict[int, ChunkAnalysis],
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    branch: str,
    repository: str,
) -> dict[tuple[int, int], IssuesReview]:
    """Run all review perspectives concurrently per chunk, keyed by (pass_number, chunk_id).

    Each (perspective × chunk) review is independent — no cross-perspective context; overlap between
    perspectives is resolved downstream by the deduplication step, so every perspective can run in
    parallel. A perspective's focus is delivered by **pull**: the prompt instructs the sandbox agent
    to `skill-get` the perspective skill (pinned to the version resolved here) over the PostHog MCP,
    rather than splicing the focus text into the prompt. Resumes by skipping (pass, chunk) pairs
    already reviewed this turn; on partial failure it logs and returns what succeeded (overlap/missing
    coverage is absorbed downstream).
    """
    existing = await sync_to_async(load_perspective_results)(team_id=team_id, report_id=report_id, head_sha=head_sha)
    perspectives = await sync_to_async(load_perspectives_for_run)(team_id)
    todo = [
        (perspective, chunk)
        for perspective in perspectives
        for chunk in chunks_data.chunks
        if (perspective.pass_number, chunk.chunk_id) not in existing
    ]
    if not todo:
        logger.info("All (perspective, chunk) reviews already completed for this turn")
        return existing

    main_template, output_schema = load_template_and_schema("issues_review")

    logger.info(f"Running {len(todo)} (perspective, chunk) review(s) for PR {pr_metadata.number}")
    results = await asyncio.gather(
        *(
            _review_one(
                perspective=perspective,
                chunk=chunk,
                main_template=main_template,
                output_schema=output_schema,
                analysis=analyses.get(chunk.chunk_id),
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                branch=branch,
                repository=repository,
            )
            for perspective, chunk in todo
        )
    )
    new = {
        (perspective.pass_number, chunk.chunk_id): review
        for (perspective, chunk), review in zip(todo, results)
        if review is not None
    }
    if len(new) != len(todo):
        logger.error(f"Failed to review {len(todo) - len(new)} (perspective, chunk) pair(s)")
    await sync_to_async(persist_perspective_results)(
        team_id=team_id, report_id=report_id, head_sha=head_sha, results=new
    )
    logger.info("Perspective review completed")
    return {**existing, **new}


def _render_prompt(
    *,
    perspective: LoadedPerspective,
    chunk: Chunk,
    main_template: Template,
    output_schema: str,
    analysis: ChunkAnalysis | None,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
) -> str:
    """Render one (perspective, chunk) review prompt, injecting the chunk's analysis as context.

    The perspective's focus isn't spliced in — the prompt instructs the agent to `skill-get` it over
    MCP — so we pass the perspective's skill name and pinned version, not its body.
    """
    chunk_analysis_context = json.dumps(analysis.model_dump(mode="json"), indent=2) if analysis is not None else None
    return main_template.render(
        **build_chunk_prompt_context(chunk, pr_metadata, pr_comments, pr_files),
        CHUNK_ANALYSIS_CONTEXT=chunk_analysis_context,
        OUTPUT_SCHEMA=output_schema,
        PERSPECTIVE_SKILL_NAME=perspective.skill_name,
        PERSPECTIVE_SKILL_VERSION=perspective.version,
    )


async def _review_one(
    *,
    perspective: LoadedPerspective,
    chunk: Chunk,
    main_template: Template,
    output_schema: str,
    analysis: ChunkAnalysis | None,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    branch: str,
    repository: str,
) -> IssuesReview | None:
    """Review one chunk through one perspective in a sandbox agent; None on failure."""
    prompt = _render_prompt(
        perspective=perspective,
        chunk=chunk,
        main_template=main_template,
        output_schema=output_schema,
        analysis=analysis,
        pr_metadata=pr_metadata,
        pr_comments=pr_comments,
        pr_files=pr_files,
    )
    review = await run_sandbox_review(
        prompt=prompt,
        system_prompt=_SYSTEM_PROMPT,
        branch=branch,
        repository=repository,
        model_to_validate=IssuesReview,
        step_name=f"issues-review-p{perspective.pass_number}-c{chunk.chunk_id}",
    )
    if review is None:
        logger.error(f"Failed to review chunk {chunk.chunk_id} (perspective {perspective.pass_number}) using sandbox")
        return None
    logger.info(f"Chunk {chunk.chunk_id} reviewed (perspective {perspective.pass_number}) successfully!")
    return review
