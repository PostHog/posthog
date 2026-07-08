from collections.abc import Callable
from typing import Any

from rest_framework.generics import GenericAPIView
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response

# A facade fetcher takes (limit, offset) and returns (page_items, total_count).
# limit is None when pagination is disabled, in which case the whole result set is returned.
FacadeFetcher = Callable[[int | None, int], tuple[list[Any], int]]


def paginate_via_facade(view: GenericAPIView, request: Request, fetch_page: FacadeFetcher) -> Response:
    """Render a DRF ``LimitOffsetPagination`` envelope from a facade function that pushes
    ``LIMIT``/``OFFSET``/``COUNT`` into SQL.

    The facade evaluates its queryset into frozen contracts to honor the product boundary, so it
    cannot hand a lazy queryset back to ``paginate_queryset`` — doing so on a materialized list would
    load the entire result set into memory just to slice one page. Instead the facade slices the
    queryset *before* mapping to contracts and returns ``(page_items, total_count)``; this helper
    reads the limit/offset from the request and assembles the standard ``{count, next, previous,
    results}`` envelope, keeping the response shape identical to a queryset-backed list view.

    Reusable across product list views (releases, stack frames, spike events — and the symbol-set
    list once it is thinned).
    """
    paginator = view.paginator
    if not isinstance(paginator, LimitOffsetPagination):
        items, _total = fetch_page(None, 0)
        return Response(view.get_serializer(items, many=True).data)

    limit = paginator.get_limit(request)
    if limit is None:
        items, _total = fetch_page(None, 0)
        return Response(view.get_serializer(items, many=True).data)

    offset = paginator.get_offset(request)
    items, total = fetch_page(limit, offset)
    # Set the count/limit/offset/request the paginator would normally derive in paginate_queryset,
    # so get_paginated_response and the next/previous links resolve correctly.
    paginator.count = total
    paginator.limit = limit
    paginator.offset = offset
    paginator.request = request
    return paginator.get_paginated_response(view.get_serializer(items, many=True).data)
