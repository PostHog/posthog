"""Render signal description markdown as Slack ``mrkdwn`` for inbox notification threads.

Signal ``content`` is usually plain prose, but externally-sourced signals (e.g. GitHub
issue bodies) carry standard markdown — headings, bullets, emphasis, ``[text](url)``
links. Dropped verbatim into a Slack ``mrkdwn`` block that shows up as literal ``**``,
``##`` and ``[text](url)`` noise, so we run it through ``markdown_to_mrkdwn``.

Slack parses mention syntax (``<@U…>``, ``<!channel>``) inside ``mrkdwn`` text, and signal
content can include untrusted external text, so escaping runs *before* conversion: raw
``&``/``<``/``>`` become inert entities the converter leaves alone, while standard markdown
links (which use no angle brackets) still convert to the well-formed ``<url|text>`` form.
"""

from __future__ import annotations

from markdown_to_mrkdwn import SlackMarkdownConverter

_CONVERTER = SlackMarkdownConverter()


def escape_mrkdwn(text: str) -> str:
    """Neutralize Slack control syntax so untrusted text can't inject mentions or links."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert markdown to Slack ``mrkdwn``, escaping mention syntax first (see module docstring)."""
    if not text:
        return text
    return _CONVERTER.convert(escape_mrkdwn(text))
