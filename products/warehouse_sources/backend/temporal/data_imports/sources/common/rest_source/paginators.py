import re
import logging
from abc import ABC, abstractmethod
from typing import Any, Literal, Optional
from urllib.parse import urljoin, urlsplit

from requests import Request, Response

from .jsonpath_utils import TJsonPath, find_values

logger = logging.getLogger(__name__)

# Where a paginator writes its pagination fields. "query" (default) mutates request.params;
# "json" mutates the POST body — for APIs that carry page/cursor/limit inside the JSON payload.
ParamLocation = Literal["query", "json"]


def _inject_param(request: Request, location: ParamLocation, name: str, value: Any) -> None:
    if location == "json":
        if request.json is None:
            request.json = {}
        request.json[name] = value
    else:
        if request.params is None:
            request.params = {}
        request.params[name] = value


class BasePaginator(ABC):
    def __init__(self) -> None:
        self._has_next_page = True

    @property
    def has_next_page(self) -> bool:
        return self._has_next_page

    def init_request(self, request: Request) -> None:  # noqa: B027
        pass

    @abstractmethod
    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None: ...

    @abstractmethod
    def update_request(self, request: Request) -> None: ...

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        """Return a JSON-serializable snapshot pointing to the next page, or
        ``None`` if this paginator does not support resume. Sources opt in by
        overriding this together with ``set_resume_state``."""
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:  # noqa: B027
        """Seed this paginator from a previously returned ``get_resume_state``
        value. After seeding, ``init_request`` must emit a request that targets
        the resumed page."""
        pass


class SinglePagePaginator(BasePaginator):
    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self._has_next_page = False

    def update_request(self, request: Request) -> None:
        pass


class BaseNextUrlPaginator(BasePaginator):
    def __init__(self) -> None:
        super().__init__()
        self._next_url: Optional[str] = None
        self._previous_next_url: Optional[str] = None

    def _advance_to(self, next_url: Optional[str], base_url: Optional[str] = None) -> None:
        """Follow ``next_url`` as the next page, or stop when there is none.

        ``next_url`` may be relative: some APIs (e.g. Ably) return the next link as
        a path like ``./stats?...``. Resolve it against ``base_url`` (the response
        URL it came from) so ``requests`` receives an absolute URL. Only the first
        request gets the base applied via ``_join_url``, so a relative next link that
        is not resolved here reaches ``requests`` with no scheme or host and fails
        with ``MissingSchema``. Resolving here also keeps the repeat guard, the resume
        state, and the allowed-host check working on absolute URLs.

        A next URL identical to the one just followed is treated as the last page:
        some APIs (e.g. Paddle) return a populated next link even on their final
        page, and following it would refetch the same page forever. Without this
        guard the sync loops until its Temporal activity timeout, which is a week
        for resumable sources.
        """
        if not next_url:
            self._has_next_page = False
            return
        # `Response.url` is a str once a request has been sent, but stays unset (or a test
        # double) before that, so only resolve against a real string base.
        if isinstance(base_url, str) and base_url:
            next_url = urljoin(base_url, next_url)
        if next_url == self._previous_next_url:
            self._handle_non_advancing_page(next_url)
            return
        self._previous_next_url = next_url
        self._next_url = next_url
        self._has_next_page = True

    def _handle_non_advancing_page(self, next_url: str) -> None:
        """Called when a response's next link equals the one just followed.

        Default: treat it as the last page and log, so end-of-data quirks complete
        the sync instead of looping. Subclasses that consider a repeated link
        hostile (e.g. Baserow's user-controlled hosts) override this to raise.
        """
        # Log only scheme/host/path: pagination links are echoed by the remote API and
        # can carry credentials in their query string for query-param-authenticated sources.
        redacted_url = urlsplit(next_url)._replace(query="", fragment="").geturl()
        logger.warning(
            "Pagination is not advancing (repeated next URL); treating as last page",
            extra={"paginator": str(self), "next_url": redacted_url},
        )
        self._has_next_page = False

    def init_request(self, request: Request) -> None:
        # Apply a seeded resume URL to the first request so a resumed run starts at the
        # saved next-page link rather than the base path.
        if self._next_url is not None:
            request.url = self._next_url
            request.params = {}

    def update_request(self, request: Request) -> None:
        if self._next_url is not None:
            request.url = self._next_url
            # The next-page URL is self-contained — it already carries every query
            # param needed. Drop the original params so `prepare_request` doesn't
            # re-append them to the URL each page; some APIs echo the received query
            # back into their next link, so re-appending compounds one copy per page
            # until the URL grows large enough for the server to reject it.
            request.params = {}

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"next_url": self._next_url} if self._has_next_page and self._next_url is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url is not None:
            self._next_url = next_url
            # Seed the repeat guard so a resumed page whose response echoes the
            # saved URL stops instead of looping on a poisoned checkpoint.
            self._previous_next_url = next_url
            self._has_next_page = True


class HeaderLinkPaginator(BaseNextUrlPaginator):
    def __init__(self, links_next_key: str = "next") -> None:
        super().__init__()
        self.links_next_key = links_next_key

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        next_link = response.links.get(self.links_next_key)
        self._advance_to(next_link.get("url") if next_link else None, response.url)

    def __str__(self) -> str:
        return f"HeaderLinkPaginator(links_next_key={self.links_next_key})"


class JSONResponsePaginator(BaseNextUrlPaginator):
    """Locates the next page URL within the JSON response body."""

    def __init__(self, next_url_path: TJsonPath = "next") -> None:
        super().__init__()
        self.next_url_path = next_url_path

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            values = find_values(self.next_url_path, response.json())
        except Exception:
            values = []
        self._advance_to(values[0] if values else None, response.url)

    def __str__(self) -> str:
        return f"JSONResponsePaginator(next_url_path={self.next_url_path})"


# Alias used by zendesk
JSONLinkPaginator = JSONResponsePaginator


class JSONResponseCursorPaginator(BasePaginator):
    def __init__(
        self,
        cursor_path: TJsonPath = "cursors.next",
        cursor_param: str = "cursor",
        param_location: ParamLocation = "query",
    ) -> None:
        super().__init__()
        self.cursor_path = cursor_path
        self.cursor_param = cursor_param
        self.param_location = param_location
        self._cursor_value: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Apply a seeded resume cursor to the first request.
        if self._cursor_value is not None:
            _inject_param(request, self.param_location, self.cursor_param, self._cursor_value)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            values = find_values(self.cursor_path, response.json())
        except Exception:
            values = []
        if values and values[0]:
            self._cursor_value = values[0]
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._cursor_value is not None:
            _inject_param(request, self.param_location, self.cursor_param, self._cursor_value)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor_value} if self._has_next_page and self._cursor_value is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor_value = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return f"JSONResponseCursorPaginator(cursor_path={self.cursor_path})"


class OffsetPaginator(BasePaginator):
    def __init__(
        self,
        limit: int,
        offset: int = 0,
        offset_param: str = "offset",
        limit_param: str = "limit",
        total_path: Optional[TJsonPath] = "total",
        total_header: Optional[str] = None,
        maximum_offset: Optional[int] = None,
        stop_after_empty_page: bool = True,
        param_location: ParamLocation = "query",
    ) -> None:
        super().__init__()
        self.limit = limit
        self.offset = offset
        self.offset_param = offset_param
        self.limit_param = limit_param
        self.total_path = total_path
        # Some APIs report the grand total in a response header (e.g. X-*-Total) rather than the body;
        # when set, this takes precedence over total_path for the stop check.
        self.total_header = total_header
        self.maximum_offset = maximum_offset
        self.stop_after_empty_page = stop_after_empty_page
        self.param_location = param_location

    def init_request(self, request: Request) -> None:
        _inject_param(request, self.param_location, self.offset_param, self.offset)
        _inject_param(request, self.param_location, self.limit_param, self.limit)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if self.stop_after_empty_page and (data is None or len(data) == 0):
            self._has_next_page = False
            return

        self.offset += self.limit

        if self.maximum_offset is not None and self.offset >= self.maximum_offset:
            self._has_next_page = False
            return

        if self.total_header:
            raw_total = response.headers.get(self.total_header)
            if raw_total is not None:
                try:
                    if self.offset >= int(raw_total):
                        self._has_next_page = False
                        return
                except (TypeError, ValueError):
                    pass

        if self.total_path:
            try:
                values = find_values(self.total_path, response.json())
                if values:
                    total = values[0]
                    if isinstance(total, int) and self.offset >= total:
                        self._has_next_page = False
                        return
            except Exception:
                pass

        if data is not None and len(data) < self.limit:
            self._has_next_page = False
            return

        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        _inject_param(request, self.param_location, self.offset_param, self.offset)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.offset already points at the next page to fetch (update_state incremented it).
        return {"offset": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"OffsetPaginator(offset={self.offset}, limit={self.limit})"


class PageNumberPaginator(BasePaginator):
    def __init__(
        self,
        base_page: int = 0,
        page: Optional[int] = None,
        page_param: str = "page",
        total_path: Optional[TJsonPath] = None,
        maximum_page: Optional[int] = None,
        stop_after_empty_page: bool = True,
        param_location: ParamLocation = "query",
    ) -> None:
        super().__init__()
        self.base_page = base_page
        self.page = page if page is not None else base_page
        self.page_param = page_param
        # jsonpath to the TOTAL NUMBER OF PAGES in the response body (e.g. "pagination.total_pages").
        # When set, pagination stops after the last page instead of paying one extra empty-page request.
        self.total_path = total_path
        self.maximum_page = maximum_page
        self.stop_after_empty_page = stop_after_empty_page
        self.param_location = param_location

    def init_request(self, request: Request) -> None:
        _inject_param(request, self.param_location, self.page_param, self.page)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if self.stop_after_empty_page and (data is None or len(data) == 0):
            self._has_next_page = False
            return

        self.page += 1

        if self.maximum_page is not None and self.page > self.maximum_page:
            self._has_next_page = False
            return

        if self.total_path:
            try:
                values = find_values(self.total_path, response.json())
                if values:
                    total_pages = values[0]
                    # self.page now points at the NEXT page; the last valid page is
                    # base_page + total_pages - 1.
                    if isinstance(total_pages, int) and self.page > self.base_page + total_pages - 1:
                        self._has_next_page = False
                        return
            except Exception:
                pass

        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        _inject_param(request, self.param_location, self.page_param, self.page)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"PageNumberPaginator(page={self.page})"


def single_entity_path(path: str) -> bool:
    """Check if path ends with a {param} pattern, indicating a single entity endpoint."""
    from pathlib import PurePosixPath

    name = PurePosixPath(path).name
    return re.search(r"\{([a-zA-Z0-9._-]+)\}", name) is not None
