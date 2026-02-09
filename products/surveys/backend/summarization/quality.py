"""Helpers for identifying low-quality survey responses.

We don't want to silently delete anything, but we *do* want to avoid wasting LLM
tokens on obvious placeholder/test responses (e.g. "asdfasdf") or keyboard mashes.
"""

from __future__ import annotations

import re

# A small, conservative list of common placeholders seen in feedback text fields.
# We intentionally keep this short to minimize false positives.
_COMMON_PLACEHOLDERS: set[str] = {
    "asdf",
    "asdfasdf",
    "qwer",
    "qwerty",
    "zxcv",
    "test",
    "testing",
    "lorem",
    "ipsum",
    "abc",
    "abcd",
}

_REPEAT_SINGLE_CHAR_RE = re.compile(r"^(.)\1{4,}$")  # e.g. "aaaaa", "11111"
_ONLY_LETTERS_RE = re.compile(r"^[a-z]+$")
_WHITESPACE_RE = re.compile(r"\s+")


def is_likely_placeholder_response(text: str) -> bool:
    """Return True if response looks like placeholder/test input.

    Heuristic rules (intentionally conservative):
    - Common placeholders ("asdf", "qwerty", "test", …)
    - Single character repeated 5+ times ("aaaaa")
    - "Keyboard mash"-like strings: long, no whitespace, mostly consonants, with a long consonant run.
    """
    normalized = (text or "").strip().lower()
    if not normalized:
        return True

    collapsed = _WHITESPACE_RE.sub("", normalized)
    if collapsed in _COMMON_PLACEHOLDERS:
        return True

    if _REPEAT_SINGLE_CHAR_RE.match(collapsed):
        return True

    # Detect long "word" with very low vowel content and a long consonant run,
    # e.g. "hjdashdjksahd" / "fasdfasdf".
    if len(collapsed) >= 10 and " " not in normalized and _ONLY_LETTERS_RE.fullmatch(collapsed):
        vowels = set("aeiou")
        vowel_count = sum(1 for c in collapsed if c in vowels)
        vowel_ratio = vowel_count / len(collapsed)

        max_consonant_run = 0
        current_run = 0
        for c in collapsed:
            if c in vowels:
                current_run = 0
            else:
                current_run += 1
                if current_run > max_consonant_run:
                    max_consonant_run = current_run

        if vowel_ratio < 0.25 and max_consonant_run >= 6:
            return True

    return False


def filter_placeholder_responses(responses: list[str]) -> tuple[list[str], list[str]]:
    """Split responses into (kept, excluded_placeholder)."""
    kept: list[str] = []
    excluded: list[str] = []

    for response in responses:
        if is_likely_placeholder_response(response):
            excluded.append(response)
        else:
            kept.append(response)

    return kept, excluded
