"""Validation for LLM-generated RenderingCanvas content.

The renderer in PostHog Code accepts a constrained React/TSX source. We refuse
anything that lets the generated code escape that sandbox (raw network access,
eval, dynamic imports, script injection) and we restrict the `{{ ... }}`
templating escape hatch to a single shape: `@api.<dotted>.<path>(<args>)`.
"""

import re

from rest_framework import serializers

MAX_CONTENT_BYTES = 256 * 1024

_FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("fetch()", re.compile(r"\bfetch\s*\(")),
    ("XMLHttpRequest", re.compile(r"\bXMLHttpRequest\b")),
    ("eval()", re.compile(r"\beval\s*\(")),
    ("new Function()", re.compile(r"\bnew\s+Function\b")),
    ("dynamic import()", re.compile(r"\bimport\s*\(")),
    ("<script> tag", re.compile(r"<script[\s>]", re.IGNORECASE)),
    ("document.write/cookie", re.compile(r"\bdocument\.(write|cookie)\b")),
    ("window.location/open", re.compile(r"\bwindow\.(location|open)\b")),
]

# An inner expression like `@api.projects.get(id, "foo")`. We forbid `{` and `}`
# inside the expression so balanced-brace parsing is never required.
_TEMPLATE_BLOCK = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_ALLOWED_TEMPLATE = re.compile(r"^@api(?:\.[a-zA-Z_][\w]*)+\([^{}]*\)$")


def validate_canvas_content(content: str) -> None:
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise serializers.ValidationError(f"Canvas content exceeds {MAX_CONTENT_BYTES} bytes.")

    for label, pattern in _FORBIDDEN_PATTERNS:
        match = pattern.search(content)
        if match:
            raise serializers.ValidationError(f"Canvas content contains forbidden pattern: {label}.")

    # Detect any `{{` or `}}` not part of a well-formed `{{ ... }}` block.
    # Pull out the well-formed blocks first, then check the remainder for stragglers.
    remainder = _TEMPLATE_BLOCK.sub("", content)
    if "{{" in remainder or "}}" in remainder:
        raise serializers.ValidationError("Canvas content has unmatched '{{' or '}}'.")

    for inner in _TEMPLATE_BLOCK.findall(content):
        expression = inner.strip()
        if not _ALLOWED_TEMPLATE.match(expression):
            raise serializers.ValidationError(
                f"Template expression is not allowed: {{{{ {expression} }}}}. "
                "Only `@api.<path>(...)` calls are permitted."
            )
