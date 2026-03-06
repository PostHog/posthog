#!/usr/bin/env python3

import re
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_jsonl(file_path: Path) -> list[dict[str, Any]]:
    """Load JSONL file and return list of JSON objects."""
    data = []
    with Path(file_path).open() as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    return data


def process_jsonl(
    jsonl_string: str,
    processor: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> str:
    """
    Process each line in a JSONL string through a processor function.

    Args:
        jsonl_string: JSONL formatted string
        processor: Function that takes a dict and returns a modified dict or None to skip

    Returns:
        Processed JSONL string
    """
    lines = jsonl_string.strip().split("\n")
    processed_lines = []

    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            processed_data = processor(data)
            if processed_data is not None:
                processed_lines.append(json.dumps(processed_data))
        except json.JSONDecodeError:
            # Keep the line if we can't parse it
            processed_lines.append(line)

    return "\n".join(processed_lines)


def filter_jsonl(
    jsonl_string: str,
    predicate: Callable[[dict[str, Any]], bool],
) -> str:
    """
    Filter JSONL lines based on a predicate function.

    Args:
        jsonl_string: JSONL formatted string
        predicate: Function that returns True to keep the line

    Returns:
        Filtered JSONL string
    """

    def filter_processor(data: dict[str, Any]) -> dict[str, Any] | None:
        return data if predicate(data) else None

    return process_jsonl(jsonl_string, filter_processor)


def extract_json_from_text(text: str | None, label: str) -> Any:
    """
    Extract JSON from text that might contain markdown formatting.

    Args:
        text: Text potentially containing JSON with markdown formatting

    Returns:
        Parsed JSON object

    Raises:
        json.JSONDecodeError: If no valid JSON could be extracted
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
