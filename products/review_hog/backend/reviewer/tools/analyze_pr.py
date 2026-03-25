import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.pr_manifest import PRManifest
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review

logger = logging.getLogger(__name__)


def generate_analyze_prompt(
    pr_metadata: PRMetadata,
    pr_files: list[PRFile],
    review_dir: Path,
) -> str:
    """Generate the PR analysis prompt."""
    prompts_dir = Path(__file__).parent.parent / "prompts" / "analyze_pr"
    schema_path = prompts_dir / "schema.json"
    with schema_path.open() as f:
        output_schema = f.read()

    env = Environment(loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape())
    template = env.get_template("prompt.jinja")

    pr_files_summary = [
        {"filename": f.filename, "status": f.status, "additions": f.additions, "deletions": f.deletions}
        for f in pr_files
    ]

    prompt = template.render(
        PR_METADATA=json.dumps(pr_metadata.model_dump(mode="json"), indent=2),
        PR_FILES=json.dumps(pr_files_summary, indent=2),
        OUTPUT_SCHEMA=output_schema,
    )

    prompt_path = review_dir / "analyze_pr_prompt.md"
    with prompt_path.open("w") as f:
        f.write(prompt)

    return prompt


async def analyze_pr(
    pr_metadata: PRMetadata,
    pr_files: list[PRFile],
    review_dir: Path,
    branch: str,
) -> None:
    """Step 1: Analyze the PR to build a product manifest."""
    output_path = review_dir / "pr-manifest.json"

    if output_path.exists() and output_path.stat().st_size > 0:
        logger.info("pr-manifest.json already exists, skipping")
        return

    prompt = generate_analyze_prompt(pr_metadata, pr_files, review_dir)

    system_prompt = (
        "You are a product analysis assistant. Analyze the PR's changed files to identify "
        "affected routes, PostHog events, and feature flags. "
        "IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."
    )

    success = await run_sandbox_review(
        prompt=prompt,
        system_prompt=system_prompt,
        branch=branch,
        output_path=str(output_path),
        model_to_validate=PRManifest,
        step_name="analyze-pr",
    )
    if not success:
        raise RuntimeError("Failed to analyze PR in sandbox")

    logger.info("PR analysis completed successfully!")
