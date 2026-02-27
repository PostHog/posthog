"""Utility functions for summarization."""

from pathlib import Path

from django.template import Context, Engine


def get_summary_cache_key(
    team_id: int,
    summarize_type: str,
    entity_id: str,
    mode: str = "minimal",
    model: str | None = None,
) -> str:
    model_key = model or "default"
    return f"llm_summary:{team_id}:{summarize_type}:{entity_id}:{mode}:{model_key}"


def load_summarization_template(template_path: str, context: dict) -> str:
    """
    Load and render a Django template file.

    Args:
        template_path: Path to .djt template file relative to summarization module
        context: Dictionary of variables to pass to template

    Returns:
        Rendered template string (plain str, not SafeString)
    """
    templates_dir = Path(__file__).parent
    engine = Engine(dirs=[str(templates_dir)])
    template = engine.get_template(template_path)
    # Disable autoescape since we're generating LLM prompts, not HTML
    # Use [:] to convert SafeString to plain str (Gemini API doesn't handle SafeString properly)
    return template.render(Context(context, autoescape=False))[:]
