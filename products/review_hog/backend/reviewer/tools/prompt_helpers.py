import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk
from products.review_hog.backend.reviewer.sandbox.code_context import prepare_code_context

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_template_and_schema(prompt_subdir: str) -> tuple[Template, str]:
    """Load a prompt's Jinja template and its output schema from reviewer/prompts/<prompt_subdir>/."""
    prompts_dir = _PROMPTS_DIR / prompt_subdir
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


def format_pr_intent(pr_metadata: PRMetadata) -> str:
    """The PR's title + description — the only PR metadata a perspective-agnostic prompt injects as intent."""
    return f"Title: {pr_metadata.title}\n\nDescription:\n{pr_metadata.body.strip() or '(no description provided)'}"


def build_chunk_prompt_context(
    chunk: Chunk,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
) -> dict[str, str]:
    """The render kwargs shared by every per-chunk prompt: code context, the chunk, its comments/files, PR intent.

    `id` / `created_at` are stripped from the comments — `id` feeds the report's last_seen_comment_id watermark,
    not the LLM, and `created_at` is metadata the prompt doesn't need.
    """
    chunk_files = [f.filename for f in chunk.files]
    pr_chunk_comments = [comment for comment in pr_comments if comment.path in chunk_files]
    pr_chunk_files = [file for file in pr_files if file.filename in chunk_files]
    return {
        "CLAUDE_CODE_CONTEXT": prepare_code_context(chunk_files, pr_chunk_files),
        "CURRENT_CHUNK": json.dumps(chunk.model_dump(), indent=2),
        "PR_INTENT": format_pr_intent(pr_metadata),
        "PR_COMMENTS": json.dumps(
            [c.model_dump(mode="json", exclude={"id", "created_at"}) for c in pr_chunk_comments], indent=2
        ),
        "PR_FILE_CHANGES": json.dumps([c.model_dump(mode="json") for c in pr_chunk_files], indent=2),
    }
