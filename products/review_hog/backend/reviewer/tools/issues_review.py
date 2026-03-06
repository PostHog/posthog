import json
import asyncio
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import IssuesReview, PassContext, PassType
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.sandbox.code_context import prepare_code_context
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review

# Configure logging
logger = logging.getLogger(__name__)

PASS_ENUM_MAP = {
    1: PassType.LOGIC_CORRECTNESS,
    2: PassType.CONTRACTS_SECURITY,
    3: PassType.PERFORMANCE_RELIABILITY,
}


async def review_chunks(
    chunks_data: ChunksList,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    review_dir: Path,
    branch: str,
) -> None:
    passes_count = len(PASS_ENUM_MAP)
    for i in range(passes_count):
        pass_number = i + 1
        logger.info(f"Starting Pass {pass_number}: {PASS_ENUM_MAP[pass_number]}")
        previous_passes_context = load_previous_pass_results(
            review_dir=review_dir,
            current_pass=pass_number,
            chunks_count=len(chunks_data.chunks),
        )
        await review_chunks_pass(
            chunks_data=chunks_data,
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            pr_files=pr_files,
            review_dir=review_dir,
            branch=branch,
            pass_number=pass_number,
            previous_passes_context=previous_passes_context,
        )
    logger.info("All review passes completed successfully!")


async def review_chunks_pass(
    chunks_data: ChunksList,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    review_dir: Path,
    branch: str,
    pass_number: int,
    previous_passes_context: list[PassContext],
) -> None:
    """Execute a single review pass for all chunks."""
    pr_id = str(pr_metadata.number)
    # Validate pass number
    if pass_number not in PASS_ENUM_MAP:
        raise ValueError(f"Invalid pass number: {pass_number}. Must be in {PASS_ENUM_MAP.keys()}")
    pass_name = PASS_ENUM_MAP[pass_number]
    chunks_count = len(chunks_data.chunks)
    logger.info(f"Starting Pass {pass_number} ({pass_name}) review for PR {pr_id} with {chunks_count} chunks")

    # Create pass-specific directories
    results_dir = review_dir / f"pass{pass_number}_results"
    results_dir.mkdir(exist_ok=True)
    # Create subdirectories for validation if needed
    (results_dir / "validation" / "prompts").mkdir(parents=True, exist_ok=True)
    (results_dir / "validation" / "summaries").mkdir(parents=True, exist_ok=True)
    (results_dir / "validation" / "combined").mkdir(parents=True, exist_ok=True)

    # Generate prompts for all chunks
    try:
        prompt_paths = await generate_prompts(
            chunks_list=chunks_data,
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            pr_files=pr_files,
            review_dir=review_dir,
            pass_number=pass_number,
            previous_passes_context=previous_passes_context,
        )
        logger.info(f"Generated {len(prompt_paths)} prompts for Pass {pass_number}")
    except Exception as e:
        logger.exception(f"Failed to generate chunk review prompts for pass {pass_number}: {e}")
        raise

    # Prepare tasks for async processing
    tasks = []
    chunks_to_process = []
    for chunk in chunks_data.chunks:
        chunk_id = chunk.chunk_id
        result_path = results_dir / f"chunk-{chunk_id}-issues-review.json"
        # Skip if result already exists
        if result_path.exists() and result_path.stat().st_size > 0:
            logger.info(f"Chunk {chunk_id} already processed, skipping...")
            continue
        # Find prompt paths for this chunk
        prompt_path = review_dir / f"pass{pass_number}_prompts" / f"chunk-{chunk_id}-code-prompt.md"
        # Create task for this chunk
        task = process_chunk(
            chunk_id=chunk_id,
            prompt_path=prompt_path,
            output_path=results_dir / f"chunk-{chunk_id}-issues-review.json",
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
    logger.info("All chunks processed successfully!")


def load_previous_pass_results(review_dir: Path, current_pass: int, chunks_count: int) -> list[PassContext]:
    """Load results from previous passes for context."""
    previous_passes = []
    # Load results from all previous passes
    for pass_num in range(1, current_pass):
        # Construct the path to the previous pass results
        chunks_results_dir = review_dir / f"pass{pass_num}_results"
        pass_issues = []
        # Collect results per chunk
        for chunk_id in range(1, chunks_count + 1):
            chunk_summary_file = chunks_results_dir / f"chunk-{chunk_id}-issues-review.json"
            if not chunk_summary_file.exists():
                raise FileNotFoundError(
                    f"Summary file not found for chunk {chunk_id} in pass {pass_num}: {chunk_summary_file}"
                )
            with chunk_summary_file.open() as f:
                issues_review = IssuesReview.model_validate_json(f.read())
            # Combine issues from all chunks
            pass_issues.extend(issues_review.issues)
        # Create pass context
        pass_context = PassContext(
            pass_number=pass_num,
            pass_type=PASS_ENUM_MAP[pass_num],
            issues=pass_issues,
        )
        previous_passes.append(pass_context)
    return previous_passes


async def generate_prompts(
    chunks_list: ChunksList,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    review_dir: Path,
    pass_number: int,
    previous_passes_context: list[PassContext],
) -> list[Path]:
    """Generate prompts for all chunks in a pass."""
    pass_type = PASS_ENUM_MAP[pass_number]
    # Setup Jinja environment - use relative path from pr_reviewer directory
    prompts_dir = Path(__file__).parent.parent / "prompts" / "issues_review"
    if not prompts_dir.exists():
        raise FileNotFoundError(f"Prompts directory not found at {prompts_dir}")
    env = Environment(
        loader=FileSystemLoader([prompts_dir, prompts_dir / "pass_contexts"]),
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

    # Load pass-specific sub-template
    try:
        pass_template = env.get_template(f"pass{pass_number}_focus.jinja")
    except Exception as e:
        raise FileNotFoundError(f"Could not load pass{pass_number}_focus.jinja template: {e}") from e

    # Create prompt directory if it doesn't exist
    prompt_dir = review_dir / f"pass{pass_number}_prompts"
    prompt_dir.mkdir(exist_ok=True)

    # Generate per-chunk prompts
    generated_prompts = []
    for chunk in chunks_list.chunks:
        chunk_id = chunk.chunk_id
        prompt_file = prompt_dir / f"chunk-{chunk_id}-code-prompt.md"
        # Skip if prompt exists
        if prompt_file.exists():
            logger.info(f"Prompt for chunk {chunk_id} already exists, skipping...")
            generated_prompts.append(prompt_file)
            continue

        # Load chunk analysis result if it exists
        chunk_analysis_context = None
        try:
            chunk_analysis_path = review_dir / f"chunk-{chunk_id}-analysis.json"
            with chunk_analysis_path.open() as f:
                chunk_analysis = ChunkAnalysis.model_validate_json(f.read())
                chunk_analysis_context = json.dumps(chunk_analysis.model_dump(mode="json"), indent=2)
                logger.info(f"Loaded chunk analysis for chunk {chunk_id}")
        except Exception as e:
            logger.warning(f"Could not load chunk analysis for chunk {chunk_id}: {e}")

        # Get files for the chunk
        chunk_files = [f.filename for f in chunk.files]
        # Filter comments and files related to chunk files
        pr_chunk_comments = [comment for comment in pr_comments if comment.path in chunk_files]
        pr_chunk_files = [file for file in pr_files if file.filename in chunk_files]

        # Generate Claude Code context with specific line ranges for changes
        claude_code_context = prepare_code_context([x.filename for x in chunk.files], pr_chunk_files)
        # Generate pass-specific content
        pass_specific_content = pass_template.render()
        # Render template with all variables
        prompt = template.render(
            CLAUDE_CODE_CONTEXT=claude_code_context,
            CURRENT_CHUNK=json.dumps(chunk.model_dump(by_alias=True), indent=2),
            CHUNK_ANALYSIS_CONTEXT=chunk_analysis_context,
            PR_METADATA=json.dumps(pr_metadata.model_dump(mode="json"), indent=2),
            PR_COMMENTS=json.dumps([c.model_dump(mode="json") for c in pr_chunk_comments], indent=2),
            PR_FILE_CHANGES=json.dumps([c.model_dump(mode="json") for c in pr_chunk_files], indent=2),
            OUTPUT_SCHEMA=output_schema,
            PASS_NUMBER=pass_number,
            PASS_NAME=pass_type.value,
            PASS_SPECIFIC_CONTENT=pass_specific_content,
            PREVIOUS_PASSES_CONTEXT=(
                json.dumps([c.model_dump(mode="json") for c in previous_passes_context])
                if previous_passes_context
                else None
            ),
        )
        # Save rendered file
        with prompt_file.open("w") as f:
            f.write(prompt)
        logger.info(f"Generated prompt for chunk {chunk_id} (Pass {pass_number})")
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
    # Prepare system prompt for issues review
    system_prompt = (
        "You are a senior code reviewer focused on identifying and documenting issues in a GitHub PR chunk.\n"
        "Focus on:\n"
        "- Identifying real issues that impact code quality, security, or performance\n"
        "- Providing specific, actionable suggestions for each issue\n"
        "- Categorizing issues by priority (must_fix, should_fix, consider)\n"
        "- Understanding the context and avoiding duplicate issues from previous passes\n"
        "- Following the specific output format requirements for IssuesReview\n"
        "IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."
    )
    try:
        success = await run_sandbox_review(
            prompt=prompt,
            system_prompt=system_prompt,
            branch=branch,
            output_path=str(output_path),
            model_to_validate=IssuesReview,
        )
        if not success:
            logger.error(f"Failed to review chunk {chunk_id} using sandbox")
            return False
    except Exception as e:
        logger.exception(f"Failed to review chunk {chunk_id} using sandbox: {e}")
        return False
    # Final success message
    logger.info(f"Chunk {chunk_id} reviewed successfully!")
    return True
