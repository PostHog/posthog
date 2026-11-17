"""Text from another tool that PostHog stores in a field it renders as Liquid."""

import re

_LIQUID_OPENING = re.compile(r"\{\{|\{%")


def literal_liquid(text: str) -> str:
    """Keeps `{{` and `{%` as plain text, so a value from another tool can't run as Liquid when PostHog sends."""
    return _LIQUID_OPENING.sub(lambda match: f'{{{{ "{match.group(0)}" }}}}', text)
