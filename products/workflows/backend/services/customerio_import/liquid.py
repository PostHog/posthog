"""Customer.io Liquid rewritten for PostHog's Liquid globals."""

import re

from posthog.dataclasses import frozen

from products.workflows.backend.facade.contracts import SnippetRoom

# Tag bodies are capped, so text full of unclosed `{{` scans in linear time.
_TAG = re.compile(r"\{\{.{0,1000}?\}\}|\{%.{0,1000}?%\}", re.DOTALL)
_UNSUBSCRIBE_TAG = re.compile(r"\{%-?\s*(?:unsubscribe_url|manage_subscription_preferences_url)\s*-?%\}")
# Customer.io prints a snippet with `{{ snippets.name }}`. The `{% snippet %}` tag is an older form.
_SNIPPET_TAG = re.compile(
    r"\{%-?\s*snippet\s+[\"']([^\"']+)[\"']\s*-?%\}"
    r"|\{\{-?\s*snippets(?:\.([\w-]+)|\[\s*[\"']([^\"']+)[\"']\s*\])\s*-?\}\}"
)
# Prints the word as a link, unlike the URL tags above.
_UNSUBSCRIBE_LINK_TAG = re.compile(r"\{%-?\s*unsubscribe\s*-?%\}")
_TRACKED_LINK_TAG = re.compile(r"\{%-?\s*cio_link\b((?:(?!%\}).){0,1000})%\}", re.DOTALL)
_TRACKED_LINK_URL = re.compile(r"\burl:\s*(?:\"([^\"]+)\"|'([^']+)'|((?:\{\{[^{}]{0,500}\}\}|[^\s\"'{}])+))")
# Customer.io tags that PostHog's Liquid doesn't know. One of them in an email stops the whole email from sending.
_UNKNOWN_TAG = re.compile(
    r"\{%-?\s*(cio_link|cio_link_id|countdown|generate_uuid|opt_out_url|random|render_liquid|subscription_topic_name"
    r"|tracking_consent_url|view_in_browser_url)\b(?:(?!%\}).){0,1000}%\}",
    re.DOTALL,
)
# Customer.io filters that PostHog's Liquid skips without an error, so the value prints unchanged.
_UNKNOWN_FILTER = re.compile(
    r"\|\s*(add_day|add_month|add_year|subtract_day|subtract_month|subtract_year|base64|base64_url_safe_decode"
    r"|base64_url_safe_encode|format_number|from_json|hex_base64|hmac_sha1|htmlencode|json_array_uniq|md5|pluralize"
    r"|rounded_currency|sha1|timezone|titlecase|to_json|where_not)\b"
)
_CAPTURE_TAG = re.compile(r"\{%-?\s*capture\s+(\w+)\s*-?%\}")
_QUOTED = re.compile(r"(\"[^\"]*\"|'[^']*')")
_OUTPUT_TAG = re.compile(r"\{\{(.{0,1000}?)\}\}", re.DOTALL)
_RAW_FILTER = re.compile(r"\|\s*raw\s*$")
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
    # Customer.io tags that were removed, and filters that were left in but do nothing.
    removed_tags: tuple[str, ...] = ()
    ignored_filters: tuple[str, ...] = ()


def rewrite(text: str | None, snippets: dict[str, str], room: SnippetRoom | None = None) -> RewrittenLiquid:
    if not text:
        return RewrittenLiquid(text=text or "")
    missing_snippets: list[str] = []
    room = room or SnippetRoom()

    def inline_snippet(match: re.Match[str]) -> str:
        name = next(group for group in match.groups() if group)
        content = snippets.get(name)
        if content is not None and len(content) <= room.remaining:
            room.remaining -= len(content)
            # A snippet is Customer.io Liquid too, so it goes through the same rewrite after this.
            return content
        missing_snippets.append(name)
        return match.group(0)

    text = _SNIPPET_TAG.sub(inline_snippet, text)
    text = _UNSUBSCRIBE_TAG.sub("{{ unsubscribe_url }}", text)
    text = _UNSUBSCRIBE_LINK_TAG.sub('<a href="{{ unsubscribe_url }}">unsubscribe</a>', text)
    text = _TRACKED_LINK_TAG.sub(_tracked_link, text)
    removed_tags = tuple(sorted(set(_UNKNOWN_TAG.findall(text))))
    text = _UNKNOWN_TAG.sub("", text)
    unsupported: set[str] = set()
    ignored_filters: set[str] = set()

    def rewrite_code(code: str) -> str:
        for name, pattern in _UNSUPPORTED.items():
            if pattern.search(code):
                unsupported.add(name)
        ignored_filters.update(_UNKNOWN_FILTER.findall(code))
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
        removed_tags=removed_tags,
        ignored_filters=tuple(sorted(ignored_filters)),
    )


def _tracked_link(match: re.Match[str]) -> str:
    found = _TRACKED_LINK_URL.search(match.group(1).removesuffix("-"))
    url = next((group for group in found.groups() if group), "") if found else ""
    # A variable instead of an address stays a tag, which is then removed with a note.
    return url if url.startswith(("http", "mailto:", "{{")) else match.group(0)


def _print_captures_raw(text: str) -> str:
    # PostHog escapes HTML in every output and Customer.io does not, so captured markup would print as text.
    captured = set(_CAPTURE_TAG.findall(text))
    if not captured:
        return text

    def add_raw(match: re.Match[str]) -> str:
        inner = match.group(1)
        open_trim = "-" if inner.startswith("-") else ""
        close_trim = "-" if inner.endswith("-") and len(inner) > len(open_trim) else ""
        body = inner[len(open_trim) : len(inner) - len(close_trim)]
        expression = body.rstrip()
        name = re.match(r"\s*(\w+)", expression)
        if name is None or name.group(1) not in captured or _RAW_FILTER.search(expression):
            return match.group(0)
        return "{{" + open_trim + expression + " | raw" + body[len(expression) :] + close_trim + "}}"

    return _OUTPUT_TAG.sub(add_raw, text)
