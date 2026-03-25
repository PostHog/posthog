import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from products.review_hog.backend.reviewer.models.posthog_context import PostHogContext
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review

logger = logging.getLogger(__name__)


def generate_context_prompt(
    review_dir: Path,
) -> str:
    """Generate the PostHog context fetching prompt."""
    prompts_dir = Path(__file__).parent.parent / "prompts" / "fetch_posthog_context"
    schema_path = prompts_dir / "schema.json"
    with schema_path.open() as f:
        output_schema = f.read()

    manifest_path = review_dir / "pr-manifest.json"
    with manifest_path.open() as f:
        pr_manifest = f.read()

    env = Environment(loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape())
    template = env.get_template("prompt.jinja")

    prompt = template.render(
        PR_MANIFEST=pr_manifest,
        OUTPUT_SCHEMA=output_schema,
    )

    prompt_path = review_dir / "fetch_posthog_context_prompt.md"
    with prompt_path.open("w") as f:
        f.write(prompt)

    return prompt


async def fetch_posthog_context(
    review_dir: Path,
    branch: str,
) -> None:
    """Step 2: Fetch PostHog usage context for affected routes and events."""
    output_path = review_dir / "product-review-context.json"

    if output_path.exists() and output_path.stat().st_size > 0:
        logger.info("product-review-context.json already exists, skipping")
        return

    prompt = generate_context_prompt(review_dir)

    system_prompt = (
        "You are a PostHog data analyst. Query PostHog using the available MCP tools "
        "to gather usage data for the affected routes and events. "
        "If a query fails, skip it and move on — don't let one failure block the output. "
        "You have ONE turn. Make all your tool calls, then output the final JSON. "
        "Do NOT end your turn without outputting the complete JSON. "
        "Do NOT output planning text, status updates, or commentary — ONLY the final JSON. "
        "IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."
    )

    success = await run_sandbox_review(
        prompt=prompt,
        system_prompt=system_prompt,
        branch=branch,
        output_path=str(output_path),
        model_to_validate=PostHogContext,
        step_name="fetch-context",
    )
    if not success:
        raise RuntimeError("Failed to fetch PostHog context in sandbox")

    logger.info("PostHog context fetching completed successfully!")
