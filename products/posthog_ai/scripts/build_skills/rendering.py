"""Rendering a skill source file through Jinja2."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, StrictUndefined


def _create_jinja_env(**extra_globals: object) -> Environment:
    """Create a Jinja2 Environment with the standard skill rendering settings."""
    env = Environment(
        # nosemgrep: python.jinja2.security.audit.autoescape-disabled-false.incorrect-autoescape-disabled -- output is Markdown for a JSON manifest, not HTML
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        lstrip_blocks=True,
        trim_blocks=True,
    )
    env.globals.update(extra_globals)
    return env


class SkillRenderer:
    """Renders skill source files to final markdown via Jinja2."""

    def __init__(self) -> None:
        from products.posthog_ai.scripts.audit_constants import audit_constants
        from products.posthog_ai.scripts.hogql_example import render_hogql_example
        from products.posthog_ai.scripts.hogql_functions import hogql_functions
        from products.posthog_ai.scripts.pydantic_schema import pydantic_schema
        from products.posthog_ai.scripts.schema_columns import schema_columns

        self.env = _create_jinja_env(
            pydantic_schema=pydantic_schema,
            render_hogql_example=render_hogql_example,
            hogql_functions=hogql_functions,
            audit_constants=audit_constants,
            schema_columns=schema_columns,
        )

    def render(self, source_file: Path) -> str:
        """Render a skill source file to its final markdown content."""
        raw = source_file.read_text()
        if source_file.suffix == ".j2":
            template = self.env.from_string(raw)
            return template.render()
        return raw
