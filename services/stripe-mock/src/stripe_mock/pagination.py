import base64
from typing import Any


def paginate_list(
    items: list[dict[str, Any]],
    url_path: str,
    limit: int = 100,
    starting_after: str | None = None,
) -> dict[str, Any]:
    """Paginate items using Stripe's List API protocol.

    The SDK reads the `url` field to construct next-page requests,
    sending `starting_after={last_item.id}` as a query param.
    """
    limit = min(max(limit, 1), 100)

    start_idx = 0
    if starting_after:
        for i, item in enumerate(items):
            if item.get("id") == starting_after:
                start_idx = i + 1
                break

    page = items[start_idx : start_idx + limit]
    has_more = start_idx + limit < len(items)

    return {
        "object": "list",
        "data": page,
        "has_more": has_more,
        "url": url_path,
    }


def paginate_search(
    items: list[dict[str, Any]],
    url_path: str,
    limit: int = 100,
    page_token: str | None = None,
) -> dict[str, Any]:
    """Paginate items using Stripe's Search API protocol.

    The SDK reads the `url` field and sends `page={next_page}` as a query param.
    We use base64-encoded offsets as opaque page tokens.
    """
    limit = min(max(limit, 1), 100)

    offset = 0
    if page_token:
        try:
            offset = int(base64.b64decode(page_token).decode())
        except (ValueError, Exception):
            offset = 0

    page = items[offset : offset + limit]
    has_more = offset + limit < len(items)
    next_page = base64.b64encode(str(offset + limit).encode()).decode() if has_more else None

    result: dict[str, Any] = {
        "object": "search_result",
        "data": page,
        "has_more": has_more,
        "url": url_path,
        "total_count": len(items),
    }
    if next_page:
        result["next_page"] = next_page

    return result
