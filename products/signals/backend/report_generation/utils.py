#!/usr/bin/env python3

import re
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_json_from_text(text: str | None, label: str) -> Any:
    """
    Extract JSON from text that might contain markdown formatting.
    """
    if text is None:
        raise ValueError(f"Text to extract JSON from text ({label}) is None")
    # Expect ```json...``` pattern first
    pattern = r"```json(?:\n|\s)*(.*)(?:\n|\s)*```"
    match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
    if match:
        # Extract JSON from the capture group
        json_text = match.group(1).strip()
        return json.loads(json_text)
    # Try to get dict-ish object from text
    pattern = r"\n(\{(?:\n|\s)*\"(?:.|\n|\s)*\})"
    match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
    if match:
        return json.loads(match.group(0))
    # Try to parse the text directly as JSON
    return json.loads(text)
