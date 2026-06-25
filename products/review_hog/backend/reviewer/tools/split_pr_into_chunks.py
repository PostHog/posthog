import logging
from pathlib import Path

from asgiref.sync import sync_to_async
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape

from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.persistence import load_chunk_set, persist_chunk_set
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review
from products.review_hog.backend.reviewer.tools.github_meta import PRComment, PRFile, PRMetadata

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)


def generate_chunking_prompt(
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
) -> str:
    """Render the chunking prompt for the sandbox agent."""
    # Load example output format
    prompts_dir = Path(__file__).parent.parent / "prompts" / "chunking"
    schema_path = prompts_dir / "schema.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found at {schema_path}")
    with schema_path.open() as f:
        output_schema = f.read()
    # Setup Jinja environment
    env = Environment(loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape())
    # Render main prompt
    try:
        prompt_template = env.get_template("prompt.jinja")
    except Exception as e:
        raise RuntimeError(f"Error loading prompt template: {e}") from e
    pr_intent = f"Title: {pr_metadata.title}\n\nDescription:\n{pr_metadata.body.strip() or '(no description provided)'}"
    return prompt_template.render(
        PR_INTENT=pr_intent,
        PR_COMMENTS=[x.model_dump_json(exclude={"id", "created_at"}) for x in pr_comments],
        PR_FILES=[x.model_dump_json() for x in pr_files],
        OUTPUT_SCHEMA=output_schema,
    )


async def split_pr_into_chunks(
    *,
    team_id: int,
    report_id: str,
    head_sha: str,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    branch: str,
    repository: str,
) -> ChunksList:
    """Split a GitHub PR into logical chunks for review, persisting the result for resume."""
    # Resume: reuse this turn's chunking if it was already computed.
    existing = await sync_to_async(load_chunk_set)(team_id=team_id, report_id=report_id, head_sha=head_sha)
    if existing is not None:
        logger.info("Reusing persisted chunk set for this turn")
        return existing

    try:
        prompt = generate_chunking_prompt(pr_metadata=pr_metadata, pr_comments=pr_comments, pr_files=pr_files)
    except (FileNotFoundError, RuntimeError) as e:
        logger.exception(f"Error generating prompt: {e}")
        raise

    system_prompt = """You are a code review assistant analyzing GitHub PRs and organizing them into logical chunks.
Focus on:
- Understanding file relationships and dependencies
- Grouping related files based on functionality
- Creating coherent, independently reviewable chunks
- Following the specific output format requirements

IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."""

    chunks = await run_sandbox_review(
        prompt=prompt,
        system_prompt=system_prompt,
        branch=branch,
        repository=repository,
        model_to_validate=ChunksList,
        step_name="chunking",
    )
    if chunks is None:
        logger.error("Failed to generate chunks using sandbox")
        raise RuntimeError("Failed to generate chunks using sandbox")

    await sync_to_async(persist_chunk_set)(team_id=team_id, report_id=report_id, head_sha=head_sha, chunks=chunks)
    logger.info("Chunking completed successfully!")
    return chunks
