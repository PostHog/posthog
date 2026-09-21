from typing import Any
from urllib.parse import urlsplit, urlunsplit


def evidence_url_key(url: Any) -> str | None:
    if not isinstance(url, str) or not url or not url.isascii() or not url.isprintable() or "\\" in url:
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username is not None or parts.password is not None:
            return None
        return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))
    except ValueError:
        return None


def evidence_quote_verified(output: dict[str, Any], tool_calls: list[dict[str, Any]]) -> bool:
    url = evidence_url_key(output.get("evidence_url"))
    quote = output.get("evidence_quote")
    if url is None or not isinstance(quote, str) or not quote.strip():
        return False
    for call in tool_calls:
        if call.get("name") != "fetch_page" or call.get("error") is not None:
            continue
        result = call.get("result")
        if not isinstance(result, dict) or evidence_url_key(result.get("url")) != url:
            continue
        markdown = result.get("markdown")
        if isinstance(markdown, str) and quote in markdown:
            return True
    return False
