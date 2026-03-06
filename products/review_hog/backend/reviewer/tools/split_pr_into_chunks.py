import logging
from pathlib import Path

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape

from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
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
    review_dir: Path,
) -> str:
    """Generate the chunking prompt for Claude Code SDK."""
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
    prompt = prompt_template.render(
        PR_METADATA=pr_metadata.model_dump_json(),
        PR_COMMENTS=[x.model_dump_json() for x in pr_comments],
        PR_FILES=[x.model_dump_json() for x in pr_files],
        OUTPUT_SCHEMA=output_schema,
    )
    with (review_dir / "chunking_prompt.md").open("w") as f:
        f.write(prompt)
    return prompt


async def split_pr_into_chunks(
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    review_dir: Path,
    branch: str,
) -> None:
    """Split a GitHub PR into logical chunks for review."""
    # Define output path for chunks.json
    output_path = review_dir / "chunks.json"

    # Check if it exists and is not empty
    if output_path.exists() and output_path.stat().st_size > 0:
        logger.info(f"Skipping chunking as {output_path} already exists")
        return

    # Generate the chunking prompt
    try:
        prompt = generate_chunking_prompt(
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            pr_files=pr_files,
            review_dir=review_dir,
        )
    except (FileNotFoundError, RuntimeError) as e:
        logger.error(f"Error generating prompt: {e}")
        raise

    system_prompt = """You are a code review assistant analyzing GitHub PRs and organizing them into logical chunks.
Focus on:
- Understanding file relationships and dependencies
- Grouping related files based on functionality
- Creating coherent, independently reviewable chunks
- Following the specific output format requirements

IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."""

    success = await run_sandbox_review(
        prompt=prompt,
        system_prompt=system_prompt,
        branch=branch,
        output_path=str(output_path),
        model_to_validate=ChunksList,
    )
    if not success:
        logger.error("Failed to generate chunks using sandbox")
        raise RuntimeError("Failed to generate chunks using sandbox")
    # Final success message
    logger.info("Chunking completed successfully!")
