"""Heuristics for detecting low-quality/test survey responses.

We use this to short-circuit LLM summarization when the input is clearly test/placeholder data
("asdf", "qwerty", random keystrokes, etc.), saving costs and avoiding misleading summaries.
"""

import re

_WHITESPACE_RE = re.compile(r"\s+")
_ALNUM_RE = re.compile(r"[a-z0-9]+")
_LETTERS_ONLY_RE = re.compile(r"^[a-z]+$")

# Common "I'm testing the input" values. Kept deliberately small and obvious.
_PLACEHOLDER_EXACT = {
    "a",
    "aa",
    "aaa",
    "aaaa",
    "abc",
    "abcd",
    "asdf",
    "asdfasdf",
    "fasdfasdf",
    "fdsa",
    "hello",
    "hi",
    "test",
    "testing",
    "qwerty",
    "qwertyuiop",
    "123",
    "1234",
    "12345",
}


def normalize_response(text: str) -> str:
    """Normalize user-entered response for classification (not for storage)."""
    cleaned = _WHITESPACE_RE.sub(" ", (text or "").strip().lower())
    # strip surrounding quotes that sometimes leak through in arrays
    return cleaned.strip("'\"")


def _is_repeated_pattern(s: str, *, max_unit_len: int = 3, min_repeats: int = 3) -> bool:
    """Detect strings like 'asdfasdf', 'ababab', 'hahahaha'."""
    if len(s) < max_unit_len * min_repeats:
        return False
    for unit_len in range(1, max_unit_len + 1):
        if len(s) % unit_len != 0:
            continue
        unit = s[:unit_len]
        repeats = len(s) // unit_len
        if repeats >= min_repeats and unit * repeats == s:
            return True
    return False


def is_placeholder_response(text: str) -> bool:
    """Return True if the response is very likely test/placeholder content."""
    s = normalize_response(text)
    if not s:
        return True

    if s in _PLACEHOLDER_EXACT:
        return True

    # "test test test", "asdf asdf"
    tokens = [t for t in s.split(" ") if t]
    if len(tokens) >= 2 and len(set(tokens)) == 1 and tokens[0] in _PLACEHOLDER_EXACT:
        return True

    # Pure repetition without spaces
    if " " not in s and _is_repeated_pattern(s):
        return True

    return False


def is_suspected_gibberish(text: str) -> bool:
    """Return True for keyboard-mash style responses.

    This is intentionally conservative and only catches obvious non-language inputs.
    """
    s = normalize_response(text)
    if not s:
        return True

    # If there are multiple words or punctuation, assume it's not gibberish.
    if " " in s:
        return False

    # Only attempt on longer, letters-only strings.
    if len(s) < 12 or not _LETTERS_ONLY_RE.match(s):
        return False

    # Very low vowel ratio is a decent signal for random keystrokes.
    vowels = sum(1 for c in s if c in "aeiou")
    vowel_ratio = vowels / max(1, len(s))
    if vowel_ratio > 0.2:
        return False

    # If it also doesn't contain any obvious alphanumeric "word-ish" segments, consider it gibberish.
    # (This primarily protects against accidental paste of symbols; letters-only already handled.)
    if not _ALNUM_RE.search(s):
        return True

    return True


def should_skip_llm_summary(responses: list[str]) -> bool:
    """Return True if the response set is dominated by placeholders/gibberish."""
    if not responses:
        return False

    cleaned = [normalize_response(r) for r in responses if normalize_response(r)]
    if not cleaned:
        return True

    low_quality = [r for r in cleaned if is_placeholder_response(r) or is_suspected_gibberish(r)]

    # For small sample sizes, require all responses to be low-quality.
    if len(cleaned) <= 5:
        return len(low_quality) == len(cleaned)

    # For larger sets, only skip if it's overwhelmingly test data.
    return (len(low_quality) / len(cleaned)) >= 0.7
