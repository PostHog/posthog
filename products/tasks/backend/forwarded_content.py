"""Framing for human text that gets forwarded into a running agent.

Thread messages and comments are written by whoever can reach the task, then handed to an
agent that reads its whole prompt as instructions. Concatenating them behind a plain prefix
lets a message read as a directive, so they go in a labelled block instead — the same shape
the client already uses for channel context and custom instructions.
"""

import re

FORWARDED_COMMENT_TAG = "forwarded_comment"

# Anything that could close the block early, so the rest of a message can't escape it and
# be read as instructions.
_TAG_PATTERN = re.compile(rf"<\s*/?\s*{FORWARDED_COMMENT_TAG}\b[^>]*>", re.IGNORECASE)
_ATTRIBUTE_UNSAFE = re.compile(r'[<>"\r\n]')


def _attribute(value: str) -> str:
    return _ATTRIBUTE_UNSAFE.sub(" ", value).strip()


def frame_forwarded_comment(*, author_name: str, content: str) -> str:
    """Wrap a person's words in a delimited block naming who wrote them."""
    body = _TAG_PATTERN.sub("", content).strip()
    return f'<{FORWARDED_COMMENT_TAG} author="{_attribute(author_name)}">\n{body}\n</{FORWARDED_COMMENT_TAG}>'
