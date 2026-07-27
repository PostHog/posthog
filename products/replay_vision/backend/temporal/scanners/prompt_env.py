"""Jinja2 environment for scanner prompts: templates under `prompts/`, custom escape that uses `<` instead of HTML's `&lt;`."""

from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined
from markupsafe import Markup


def _prompt_escape(value: Any) -> Markup:
    """Escape `<` so user content can't forge a delimiter tag inside the prompt."""
    if isinstance(value, Markup):
        # Already escaped (e.g. `tojson` output) — skip the full-string copy + replace.
        # Foot-gun: `{{ var | safe }}` and direct `Markup` inputs bypass this check too; avoid both in templates.
        return value
    return Markup(str(value).replace("<", "\\u003c"))


_env = Environment(
    loader=PackageLoader("products.replay_vision.backend.temporal.scanners", "prompts"),
    autoescape=True,
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=True,
    undefined=StrictUndefined,
    finalize=_prompt_escape,
)
# Compact `tojson` output — Gemini parses fine without whitespace, and indent burns prompt tokens.
_env.policies["json.dumps_kwargs"] = {"separators": (",", ":")}


def render_prompt(template_name: str, **context: Any) -> str:
    """Render a scanner prompt template with the given context."""
    return _env.get_template(template_name).render(**context)
