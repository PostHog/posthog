import json
import logging
from fnmatch import fnmatch
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.product_review_output import ProductReviewRaw, ProductReviewRewritten
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review

logger = logging.getLogger(__name__)


def _filter_taxonomy_for_changed_files(taxonomy: dict, changed_files: list[str]) -> dict:
    """Return a copy of the taxonomy containing only products/features whose code_paths match changed files."""

    def _any_path_matches(code_paths: list[str]) -> bool:
        return any(fnmatch(f, pattern) for pattern in code_paths for f in changed_files)

    matched_products = []
    for product in taxonomy.get("products", []):
        product_matches = _any_path_matches(product.get("code_paths", []))

        matched_features = [
            feat for feat in product.get("features", []) if _any_path_matches(feat.get("code_paths", []))
        ]

        if product_matches or matched_features:
            filtered = {**product, "features": matched_features if matched_features else product.get("features", [])}
            matched_products.append(filtered)

    return {"products": matched_products}


def _load_changed_filenames(review_dir: Path) -> list[str]:
    """Read the list of changed filenames from pr_files.jsonl."""
    pr_files_path = review_dir / "pr_files.jsonl"
    if not pr_files_path.exists():
        return []
    filenames = []
    with pr_files_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                filenames.append(json.loads(line).get("filename", ""))
    return [f for f in filenames if f]


def generate_summary_prompt(
    pr_metadata: PRMetadata,
    review_dir: Path,
    pr_comments: str | None = None,
) -> str:
    """Generate the product review summary prompt."""
    prompts_dir = Path(__file__).parent.parent / "prompts" / "write_summary"
    schema_path = prompts_dir / "schema.json"
    with schema_path.open() as f:
        output_schema = f.read()

    references_dir = Path(__file__).parent.parent / "references"
    with (references_dir / "product_engineer_persona.md").open() as f:
        persona = f.read()
    with (references_dir / "taste.md").open() as f:
        taste = f.read()

    with (references_dir / "posthog-com_contextualized_taxonomy.json").open() as f:
        full_taxonomy = json.load(f)
    changed_files = _load_changed_filenames(review_dir)
    filtered_taxonomy = _filter_taxonomy_for_changed_files(full_taxonomy, changed_files)
    matched_products = filtered_taxonomy.get("products", [])
    product_taxonomy = json.dumps(filtered_taxonomy, indent=2) if matched_products else None
    logger.info(
        "Taxonomy filtered: %d/%d products matched for %d changed files",
        len(matched_products),
        len(full_taxonomy.get("products", [])),
        len(changed_files),
    )

    manifest_path = review_dir / "pr-manifest.json"
    with manifest_path.open() as f:
        pr_manifest = f.read()

    context_path = review_dir / "product-review-context.json"
    with context_path.open() as f:
        posthog_context = f.read()

    env = Environment(loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape())
    template = env.get_template("prompt.jinja")

    prompt = template.render(
        PR_METADATA=json.dumps(pr_metadata.model_dump(mode="json"), indent=2),
        PR_MANIFEST=pr_manifest,
        POSTHOG_CONTEXT=posthog_context,
        PRODUCT_TAXONOMY=product_taxonomy,
        PERSONA=persona,
        TASTE=taste,
        OUTPUT_SCHEMA=output_schema,
        PR_COMMENTS=pr_comments,
    )

    prompt_path = review_dir / "write_summary_prompt.md"
    with prompt_path.open("w") as f:
        f.write(prompt)

    return prompt


async def write_product_review(
    pr_metadata: PRMetadata,
    review_dir: Path,
    branch: str,
    pr_comments: str | None = None,
) -> None:
    """Step 3: Write the product review summary."""
    output_path = review_dir / "product-review-raw.json"

    if output_path.exists() and output_path.stat().st_size > 0:
        logger.info("product-review-raw.json already exists, skipping")
        return

    prompt = generate_summary_prompt(pr_metadata, review_dir, pr_comments=pr_comments)

    system_prompt = (
        "You are a senior PostHog product engineer writing a concise, opinionated product review. "
        "Focus on what this change means for users, backed by data, with a strong point of view. "
        "IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."
    )

    success = await run_sandbox_review(
        prompt=prompt,
        system_prompt=system_prompt,
        branch=branch,
        output_path=str(output_path),
        model_to_validate=ProductReviewRaw,
        step_name="write-summary",
    )
    if not success:
        raise RuntimeError("Failed to write product review in sandbox")

    logger.info("Raw product review written successfully!")


RELEVANCE_THRESHOLD = 5


def _assemble_markdown(
    rewritten: ProductReviewRewritten, context_path: Path, recording_path: Path | None = None
) -> str:
    """Assemble final markdown from rewritten items, filtering by relevance threshold."""
    sections: list[str] = []
    sections.append("## Product Review")
    sections.append("")
    sections.append(rewritten.one_liner)

    risks = [r for r in rewritten.risk_signals if r.product_relevance >= RELEVANCE_THRESHOLD]
    if risks:
        sections.append("")
        sections.append(f"<details>\n<summary>:warning: {len(risks)} risk signal(s)</summary>\n")
        for r in risks:
            sections.append(f"- {r.rewritten}")
        sections.append("\n</details>")

    questions = [q for q in rewritten.questions if q.product_relevance >= RELEVANCE_THRESHOLD]
    if questions:
        sections.append("")
        sections.append(f"<details>\n<summary>:question: {len(questions)} question(s) for the author</summary>\n")
        for i, q in enumerate(questions, 1):
            sections.append(f"{i}. {q.rewritten}")
        sections.append("\n</details>")

    taste = [t for t in rewritten.taste if t.product_relevance >= RELEVANCE_THRESHOLD]
    if taste:
        sections.append("")
        sections.append("<details>\n<summary>:eye: Taste</summary>\n")
        for t in taste:
            sections.append(f"- {t.rewritten}")
        sections.append("\n</details>")

    # Add recording link if available
    if recording_path and recording_path.exists():
        try:
            with recording_path.open() as f:
                recording = json.load(f)
            session_url = recording.get("session_url")
            if session_url:
                sections.append("")
                sections.append(f"---\n:movie_camera: [Watch feature recording]({session_url})")
        except Exception:
            pass

    # Add replay links from context if available
    try:
        with context_path.open() as f:
            context = json.load(f)
        replay_links = []
        for route in context.get("routes", []):
            if route.get("pageviews_30d", 0) > 0 and route.get("replay_url"):
                patterns = route.get("url_patterns", [])
                label = patterns[0] if patterns else route.get("route_key", "")
                replay_links.append(f"[{label}]({route['replay_url']})")
        if replay_links:
            sections.append("")
            sections.append(f"---\n:tv: Watch users: {' / '.join(replay_links)}")
    except Exception:
        pass

    return "\n".join(sections)


def publish_product_review(
    owner: str,
    repo: str,
    pr_number: int,
    review_dir: Path,
) -> None:
    """Assemble and write the final product review markdown."""
    rewritten_path = review_dir / "product-review-rewritten.json"
    with rewritten_path.open() as f:
        rewritten = ProductReviewRewritten.model_validate_json(f.read())

    context_path = review_dir / "product-review-context.json"
    recording_path = review_dir / "recording.json"
    markdown = _assemble_markdown(rewritten, context_path, recording_path)

    output_path = review_dir / "product-review.md"
    with output_path.open("w") as f:
        f.write(markdown)

    logger.info(f"Product review written to {output_path}")
