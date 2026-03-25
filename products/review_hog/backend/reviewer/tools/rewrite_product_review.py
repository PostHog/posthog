import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.product_review_output import ProductReviewRaw, ProductReviewRewritten
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review

logger = logging.getLogger(__name__)


def generate_rewrite_prompt(
    pr_metadata: PRMetadata,
    review_dir: Path,
) -> str:
    """Generate the rewrite prompt from raw review + context."""
    prompts_dir = Path(__file__).parent.parent / "prompts" / "rewrite_review"
    schema_path = prompts_dir / "schema.json"
    with schema_path.open() as f:
        output_schema = f.read()

    references_dir = Path(__file__).parent.parent / "references"
    with (references_dir / "product_engineer_persona.md").open() as f:
        persona = f.read()
    with (references_dir / "taste.md").open() as f:
        taste = f.read()

    manifest_path = review_dir / "pr-manifest.json"
    with manifest_path.open() as f:
        pr_manifest = f.read()

    context_path = review_dir / "product-review-context.json"
    with context_path.open() as f:
        posthog_context = f.read()

    raw_path = review_dir / "product-review-raw.json"
    with raw_path.open() as f:
        raw_review = ProductReviewRaw.model_validate_json(f.read())

    env = Environment(loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape())
    template = env.get_template("prompt.jinja")

    prompt = template.render(
        PR_METADATA=json.dumps(pr_metadata.model_dump(mode="json"), indent=2),
        PR_MANIFEST=pr_manifest,
        POSTHOG_CONTEXT=posthog_context,
        PERSONA=persona,
        TASTE=taste,
        ONE_LINER=raw_review.one_liner,
        RISK_SIGNALS=[r.model_dump() for r in raw_review.risk_signals],
        QUESTIONS=[q.model_dump() for q in raw_review.questions],
        TASTE_ITEMS=[t.model_dump() for t in raw_review.taste],
        OUTPUT_SCHEMA=output_schema,
    )

    prompt_path = review_dir / "rewrite_review_prompt.md"
    with prompt_path.open("w") as f:
        f.write(prompt)

    return prompt


async def rewrite_product_review(
    pr_metadata: PRMetadata,
    review_dir: Path,
    branch: str,
) -> None:
    """Rewrite raw review items in product language and score relevance."""
    output_path = review_dir / "product-review-rewritten.json"

    if output_path.exists() and output_path.stat().st_size > 0:
        logger.info("product-review-rewritten.json already exists, skipping")
        return

    prompt = generate_rewrite_prompt(pr_metadata, review_dir)

    system_prompt = (
        "You are an editor who rewrites technical code review observations into product language. "
        "Remove all code identifiers and describe everything in terms of user behavior. "
        "IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."
    )

    success = await run_sandbox_review(
        prompt=prompt,
        system_prompt=system_prompt,
        branch=branch,
        output_path=str(output_path),
        model_to_validate=ProductReviewRewritten,
        step_name="rewrite-review",
    )
    if not success:
        raise RuntimeError("Failed to rewrite product review in sandbox")

    logger.info("Product review rewritten successfully!")
