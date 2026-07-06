"""Tests for prompt sanitization in reviewer.py."""

import sys

import pytest
from unittest.mock import MagicMock

# reviewer.py is imported by a uv-script; its `claude_agent_sdk` dep is
# installed by `uv run`, not the test venv. Stub the modules it imports.
sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

from reviewer import _sanitize_untrusted  # noqa: E402


@pytest.mark.parametrize(
    "text,expected",
    [
        # Reviewer bots express verdicts as emoji in review bodies; stripping
        # them garbles quoted comments into text a later run can misread as
        # an injection attempt.
        pytest.param(
            "both have 👀 reactions — that overrides the 👍s present.",
            "both have 👀 reactions — that overrides the 👍s present.",
            id="emoji-and-dash-survive",
        ),
        pytest.param("ein Häkchen ✓ 中文", "ein Häkchen ✓ 中文", id="non-ascii-text-survives"),
        pytest.param("zero\u200bwidth\u200e", "zerowidth", id="zero-width-stripped"),
        # ZWJ interleaving (i\u200dg\u200dn\u200do\u200dr\u200de) is a smuggling vector, so it
        # is stripped too; composite emoji degrade to visible components.
        pytest.param("i\u200dg\u200dnore 🧑\u200d💻", "ignore 🧑💻", id="zwj-stripped-emoji-degrades-visibly"),
        pytest.param("a\u202egnihton\u202c od\u2066b\u2069\u061c", "agnihton odb", id="bidi-controls-stripped"),
        pytest.param("hidden\U000e0041\U000e0042tag", "hiddentag", id="tags-block-smuggling-stripped"),
        pytest.param("bell\x07cr\rok\ntab\t.", "bellcrok\ntab\t.", id="control-chars-stripped-keeps-nl-tab"),
    ],
)
def test_sanitize_untrusted_strips_invisible_keeps_visible(text: str, expected: str) -> None:
    assert _sanitize_untrusted(text) == expected
