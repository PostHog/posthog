"""Validation for LLM-generated RenderingCanvas content.

The renderer in PostHog Code evaluates the source as a script inside a sandboxed
iframe with `useApi`, `api`, React, and PostHog primitives injected as globals.
We refuse anything that lets the generated code escape that sandbox (raw network
access, eval, dynamic imports, script injection).
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


def validate_canvas_content(content: str) -> None:
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise serializers.ValidationError(f"Canvas content exceeds {MAX_CONTENT_BYTES} bytes.")

    for label, pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(content):
            raise serializers.ValidationError(f"Canvas content contains forbidden pattern: {label}.")
