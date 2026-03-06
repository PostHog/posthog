import json
import asyncio
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.sandbox.code_context import prepare_code_context
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review

# Configure logging
logger = logging.getLogger(__name__)


async def analyze_chunks(
    chunks_data: ChunksList,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    review_dir: Path,
    branch: str,
) -> None:
    """Analyze all chunks to understand their purpose and architecture."""
    pr_id = str(pr_metadata.number)
    logger.info(f"Starting chunk analysis for PR {pr_id} with {len(chunks_data.chunks)} chunks")

    # Generate prompts for all chunks
    try:
        prompt_paths = await generate_prompts(
            chunks_list=chunks_data,
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            pr_files=pr_files,
            review_dir=review_dir,
        )
        logger.info(f"Generated {len(prompt_paths)} prompts for chunk analysis")
    except Exception as e:
        logger.error(f"Failed to generate chunk analysis prompts: {e}")
        raise

    # Prepare tasks for async processing
    tasks = []
    chunks_to_process = []
    for chunk in chunks_data.chunks:
        chunk_id = chunk.chunk_id
        result_path = review_dir / f"chunk-{chunk_id}-analysis.json"
        # Skip if result already exists
        if result_path.exists() and result_path.stat().st_size > 0:
            logger.info(f"Chunk {chunk_id} already analyzed, skipping...")
            continue
        # Find prompt path for this chunk
        prompt_path = review_dir / "prompts" / f"chunk-{chunk_id}-prompt.md"
        # Create task for this chunk
        task = process_chunk(
            chunk_id=chunk_id,
            prompt_path=prompt_path,
            output_path=result_path,
            branch=branch,
        )
        tasks.append(task)
        chunks_to_process.append(chunk_id)

    if not tasks:
        logger.info("No chunks to process")
        return

    logger.info(f"Processing {len(tasks)} chunks async...")
    # Process chunks concurrently
    results = await asyncio.gather(*tasks)
    # Filter out failed chunks
    if not all(results):
        logger.error(f"Failed to process some chunks ({[x for x in results if not x]})")
        return
    logger.info("All chunks analyzed successfully!")


async def generate_prompts(
    chunks_list: ChunksList,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    review_dir: Path,
) -> list[Path]:
    """Generate analysis prompts for all chunks."""
    # Setup Jinja environment - use relative path from pr_reviewer directory
    prompts_dir = Path(__file__).parent.parent / "prompts" / "chunk_analysis"
    if not prompts_dir.exists():
        raise FileNotFoundError(f"Prompts directory not found at {prompts_dir}")
    env = Environment(
        loader=FileSystemLoader(prompts_dir),
        autoescape=select_autoescape(),
    )
    try:
        template = env.get_template("prompt.jinja")
    except Exception as e:
        raise FileNotFoundError(f"Could not load prompt.jinja template: {e}") from e

    # Load output schema
    schema_path = prompts_dir / "schema.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found at {schema_path}")
    with schema_path.open() as f:
        output_schema = f.read()

    # Create prompt directory if it doesn't exist
    prompt_dir = review_dir / "prompts"
    prompt_dir.mkdir(exist_ok=True)

    # Generate per-chunk prompts
    generated_prompts = []
    for chunk in chunks_list.chunks:
        chunk_id = chunk.chunk_id
        prompt_file = prompt_dir / f"chunk-{chunk_id}-prompt.md"
        # Skip if prompt exists
        if prompt_file.exists():
            logger.info(f"Prompt for chunk {chunk_id} already exists, skipping...")
            generated_prompts.append(prompt_file)
            continue

        # Get files for the chunk
        chunk_files = [f.filename for f in chunk.files]
        # Filter comments and files related to chunk files
        pr_chunk_comments = [comment for comment in pr_comments if comment.path in chunk_files]
        pr_chunk_files = [file for file in pr_files if file.filename in chunk_files]

        # Generate Claude Code context with specific line ranges for changes
        claude_code_context = prepare_code_context([x.filename for x in chunk.files], pr_chunk_files)
        # Render template with all variables
        prompt = template.render(
            CLAUDE_CODE_CONTEXT=claude_code_context,
            CURRENT_CHUNK=json.dumps(chunk.model_dump(by_alias=True), indent=2),
            PR_METADATA=json.dumps(pr_metadata.model_dump(mode="json"), indent=2),
            PR_COMMENTS=json.dumps([c.model_dump(mode="json") for c in pr_chunk_comments], indent=2),
            PR_FILE_CHANGES=json.dumps([c.model_dump(mode="json") for c in pr_chunk_files], indent=2),
            OUTPUT_SCHEMA=output_schema,
        )
        # Save rendered file
        with prompt_file.open("w") as f:
            f.write(prompt)
        logger.info(f"Generated prompt for chunk {chunk_id}")
        generated_prompts.append(prompt_file)
    return generated_prompts


async def process_chunk(
    chunk_id: int,
    prompt_path: Path,
    output_path: Path,
    branch: str,
) -> bool:
    """Process a single chunk through a sandbox agent."""
    # Read prompt content
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    with prompt_path.open() as f:
        prompt = f.read()
    # Prepare system prompt for chunk analysis
    system_prompt = """You are a senior software engineer analyzing a chunk of code changes in a GitHub PR.
Focus on:
- Understanding the purpose and goal of the changes
- Analyzing the architecture and design patterns
- Identifying dependencies and integration points
- Providing technical insights about the implementation
IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."""
    try:
        success = await run_sandbox_review(
            prompt=prompt,
            system_prompt=system_prompt,
            branch=branch,
            output_path=str(output_path),
            model_to_validate=ChunkAnalysis,
        )
        if not success:
            logger.error(f"Failed to analyze chunk {chunk_id} using sandbox")
            return False
    except Exception as e:
        logger.error(f"Failed to analyze chunk {chunk_id} using sandbox: {e}")
        return False
    # Final success message
    logger.info(f"Chunk {chunk_id} analyzed successfully!")
    return True
