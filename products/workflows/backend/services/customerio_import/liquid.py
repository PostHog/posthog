"""Customer.io Liquid rewritten for PostHog's Liquid globals."""

import re

from posthog.dataclasses import frozen

_TAG = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
_UNSUBSCRIBE_TAG = re.compile(r"\{%-?\s*(?:unsubscribe_url|manage_subscription_preferences_url)\s*-?%\}")
_SNIPPET_TAG = re.compile(r"\{%-?\s*snippet\s+[\"']([^\"']+)[\"']\s*-?%\}")
_CAPTURE_TAG = re.compile(r"\{%-?\s*capture\s+(\w+)\s*-?%\}")
_QUOTED = re.compile(r"(\"[^\"]*\"|'[^']*')")
_OUTPUT_TAG = re.compile(r"\{\{(-?)(\s*)(\w+)(.*?)(\s*)(-?)\}\}", re.DOTALL)
# Customer.io's `customer.id` is the id the team identifies people with, which is the distinct id in PostHog.
_RENAMES = (
    (re.compile(r"(?<![\w.])customer\.id\b"), "event.distinct_id"),
    (re.compile(r"(?<![\w.])customer(?=[.\[])"), "person.properties"),
    (
        re.compile(r"(?<![\w.])event(?=\.(?!properties\b|distinct_id\b|event\b|uuid\b|timestamp\b)|\[)"),
        "event.properties",
    ),
    (re.compile(r"(?<![\w.])event_name\b"), "event.event"),
    (re.compile(r"(?<![\w.])event_id\b"), "event.uuid"),
    (re.compile(r"(?<![\w.])event_timestamp\b"), "event.timestamp"),
    (re.compile(r"(?<![\w.])trigger(?=[.\[])"), "event.properties"),
)
_UNSUPPORTED = {
    "journey": re.compile(r"(?<![\w.])journey\."),
    "campaign": re.compile(r"(?<![\w.])campaign\."),
    "message": re.compile(r"(?<![\w.])message\."),
    "delivery_id": re.compile(r"(?<![\w.])delivery_id\b"),
}


@frozen
class RewrittenLiquid:
    text: str
    # Customer.io globals the text uses that PostHog has no value for, like `journey`.
    unsupported_globals: tuple[str, ...] = ()
    # Snippets the text includes that the import was not given.
    missing_snippets: tuple[str, ...] = ()


def rewrite(text: str | None, snippets: dict[str, str]) -> RewrittenLiquid:
    if not text:
        return RewrittenLiquid(text=text or "")
    missing_snippets: list[str] = []

    def inline_snippet(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in snippets:
            # A snippet is Customer.io Liquid too, so it goes through the same rewrite after this.
            return snippets[name]
        missing_snippets.append(name)
        return match.group(0)

    text = _SNIPPET_TAG.sub(inline_snippet, text)
    text = _UNSUBSCRIBE_TAG.sub("{{ unsubscribe_url }}", text)
    unsupported: set[str] = set()

    def rewrite_code(code: str) -> str:
        for name, pattern in _UNSUPPORTED.items():
            if pattern.search(code):
                unsupported.add(name)
        for pattern, replacement in _RENAMES:
            code = pattern.sub(replacement, code)
        return code

    def rewrite_tag(match: re.Match[str]) -> str:
        # Odd parts are quoted strings, which are literal text and keep what they say.
        parts = _QUOTED.split(match.group(0))
        return "".join(part if index % 2 else rewrite_code(part) for index, part in enumerate(parts))

    text = _TAG.sub(rewrite_tag, text)
    text = _print_captures_raw(text)
    return RewrittenLiquid(
        text=text,
        unsupported_globals=tuple(sorted(unsupported)),
        missing_snippets=tuple(dict.fromkeys(missing_snippets)),
    )


def _print_captures_raw(text: str) -> str:
    # PostHog escapes HTML in every output and Customer.io does not, so captured markup would print as text.
    captured = set(_CAPTURE_TAG.findall(text))
    if not captured:
        return text

    def add_raw(match: re.Match[str]) -> str:
        open_trim, lead, name, rest, trail, close_trim = match.groups()
        if name not in captured or re.search(r"\|\s*raw\s*$", rest):
            return match.group(0)
        return "{{" + open_trim + lead + name + rest + " | raw" + trail + close_trim + "}}"

    return _OUTPUT_TAG.sub(add_raw, text)
