"""Utility functions for summarization."""

from pathlib import Path

from django.template import Context, Engine


def load_summarization_template(template_path: str, context: dict) -> str:
    """
    Load and render a Django template file.

    Args:
        template_path: Path to .djt template file relative to summarization module
        context: Dictionary of variables to pass to template

    Returns:
        Rendered template string
    """
    templates_dir = Path(__file__).parent
    engine = Engine(dirs=[str(templates_dir)])
    template = engine.get_template(template_path)
    return template.render(Context(context))
