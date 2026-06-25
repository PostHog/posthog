import json
import asyncio
import logging
from pathlib import Path

from asgiref.sync import sync_to_async
from jinja2 import Environment, FileSystemLoader, Template, select_autoescape

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList
from products.review_hog.backend.reviewer.persistence import load_chunk_analyses, persist_chunk_analyses
from products.review_hog.backend.reviewer.sandbox.code_context import prepare_code_context
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review

# Configure logging
logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior software engineer analyzing a chunk of code changes in a GitHub PR.
Focus on:
- Understanding the purpose and goal of the changes
- Analyzing the architecture and design patterns
- Identifying dependencies and integration points
- Providing technical insights about the implementation
IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."""


async def analyze_chunks(
    *,
    team_id: int,
    report_id: str,
    head_sha: str,
    chunks_data: ChunksList,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    branch: str,
    repository: str,
) -> dict[int, ChunkAnalysis]:
    """Analyze every chunk to understand its purpose and architecture (best-effort, per-chunk resume).

    Returns the chunk analyses keyed by chunk id. Resumes by skipping chunks already analysed this
    turn; on partial failure it logs and returns what succeeded (analysis is informational, so a
    missing chunk doesn't fail the run).
    """
    existing = await sync_to_async(load_chunk_analyses)(team_id=team_id, report_id=report_id, head_sha=head_sha)
    todo = [chunk for chunk in chunks_data.chunks if chunk.chunk_id not in existing]
    if not todo:
        logger.info("All chunks already analyzed for this turn")
        return existing

    logger.info(f"Analyzing {len(todo)} chunk(s) for PR {pr_metadata.number}")
    template, output_schema = _load_template_and_schema()
    results = await asyncio.gather(
        *(
            _analyze_one_chunk(
                chunk=chunk,
                template=template,
                output_schema=output_schema,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                branch=branch,
                repository=repository,
            )
            for chunk in todo
        )
    )
    new = {chunk.chunk_id: analysis for chunk, analysis in zip(todo, results) if analysis is not None}
    if len(new) != len(todo):
        logger.error(f"Failed to analyze {len(todo) - len(new)} chunk(s)")
    await sync_to_async(persist_chunk_analyses)(team_id=team_id, report_id=report_id, head_sha=head_sha, analyses=new)
    logger.info("Chunk analysis completed")
    return {**existing, **new}


def _load_template_and_schema() -> tuple[Template, str]:
    """Load the chunk-analysis Jinja template and its output schema (static package assets)."""
    prompts_dir = Path(__file__).parent.parent / "prompts" / "chunk_analysis"
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
    chunk: Chunk,
    template: Template,
    output_schema: str,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
) -> str:
    """Render the analysis prompt for one chunk (code context + the chunk's files/comments)."""
    chunk_files = [f.filename for f in chunk.files]
    pr_chunk_comments = [comment for comment in pr_comments if comment.path in chunk_files]
    pr_chunk_files = [file for file in pr_files if file.filename in chunk_files]
    claude_code_context = prepare_code_context(chunk_files, pr_chunk_files)
    pr_intent = f"Title: {pr_metadata.title}\n\nDescription:\n{pr_metadata.body.strip() or '(no description provided)'}"
    return template.render(
        CLAUDE_CODE_CONTEXT=claude_code_context,
        CURRENT_CHUNK=json.dumps(chunk.model_dump(by_alias=True), indent=2),
        PR_INTENT=pr_intent,
        PR_COMMENTS=json.dumps(
            [c.model_dump(mode="json", exclude={"id", "created_at"}) for c in pr_chunk_comments], indent=2
        ),
        PR_FILE_CHANGES=json.dumps([c.model_dump(mode="json") for c in pr_chunk_files], indent=2),
        OUTPUT_SCHEMA=output_schema,
    )


async def _analyze_one_chunk(
    *,
    chunk: Chunk,
    template: Template,
    output_schema: str,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    branch: str,
    repository: str,
) -> ChunkAnalysis | None:
    """Analyze a single chunk through a sandbox agent; None on failure."""
    prompt = _render_prompt(chunk, template, output_schema, pr_metadata, pr_comments, pr_files)
    analysis = await run_sandbox_review(
        prompt=prompt,
        system_prompt=_SYSTEM_PROMPT,
        branch=branch,
        repository=repository,
        model_to_validate=ChunkAnalysis,
        step_name=f"chunk-analysis-{chunk.chunk_id}",
    )
    if analysis is None:
        logger.error(f"Failed to analyze chunk {chunk.chunk_id} using sandbox")
        return None
    logger.info(f"Chunk {chunk.chunk_id} analyzed successfully!")
    return analysis
