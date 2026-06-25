import json
import asyncio
import logging
from pathlib import Path

from asgiref.sync import sync_to_async
from jinja2 import Environment, FileSystemLoader, Template, select_autoescape

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import IssuesReview
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList
from products.review_hog.backend.reviewer.persistence import load_perspective_results, persist_perspective_results
from products.review_hog.backend.reviewer.sandbox.code_context import prepare_code_context
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review
from products.review_hog.backend.reviewer.skill_loader import LoadedPerspective, load_perspectives_for_run

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

    main_template, output_schema = _load_review_assets()

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


def _load_review_assets() -> tuple[Template, str]:
    """Load the issues-review Jinja template and its output schema."""
    prompts_dir = Path(__file__).parent.parent / "prompts" / "issues_review"
    if not prompts_dir.exists():
        raise FileNotFoundError(f"Prompts directory not found at {prompts_dir}")
    env = Environment(loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape())
    try:
        template = env.get_template("prompt.jinja")
    except Exception as e:
        raise FileNotFoundError(f"Could not load prompt.jinja template: {e}") from e
    schema_path = prompts_dir / "schema.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found at {schema_path}")
    with schema_path.open() as f:
        return template, f.read()


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
    chunk_files = [f.filename for f in chunk.files]
    pr_chunk_comments = [comment for comment in pr_comments if comment.path in chunk_files]
    pr_chunk_files = [file for file in pr_files if file.filename in chunk_files]
    claude_code_context = prepare_code_context(chunk_files, pr_chunk_files)
    pr_intent = f"Title: {pr_metadata.title}\n\nDescription:\n{pr_metadata.body.strip() or '(no description provided)'}"
    return main_template.render(
        CLAUDE_CODE_CONTEXT=claude_code_context,
        CURRENT_CHUNK=json.dumps(chunk.model_dump(by_alias=True), indent=2),
        CHUNK_ANALYSIS_CONTEXT=chunk_analysis_context,
        PR_INTENT=pr_intent,
        PR_COMMENTS=json.dumps(
            [c.model_dump(mode="json", exclude={"id", "created_at"}) for c in pr_chunk_comments], indent=2
        ),
        PR_FILE_CHANGES=json.dumps([c.model_dump(mode="json") for c in pr_chunk_files], indent=2),
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
