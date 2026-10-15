import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, ClassVar, Generic, Optional, ParamSpec, TypeVar

import stripe as stripe_lib
from stripe import CreditNote, CreditNoteLineItem, Invoice, InvoiceLineItem, ListObject, StripeClient
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.request_pacer import (
    RequestPacer,
    submit_with_context,
)

# Stripe's test-mode read limit is 25 requests/s and the live-mode limit is 100. Five workers stay
# under both, and the page fetch is the longer leg of an iteration, so more would not shorten a sweep.
LINE_FETCH_CONCURRENCY = 5
# Fast responses could still let five workers exceed the test-mode limit, so request starts are paced
# independently of the worker count. The limit is per account, shared with every other caller.
LINE_REQUESTS_PER_SECOND = 20.0

_P = ParamSpec("_P")
_T = TypeVar("_T")
_ParentT = TypeVar("_ParentT", Invoice, CreditNote)
_LineT = TypeVar("_LineT", InvoiceLineItem, CreditNoteLineItem)

# Receives the Retry-After seconds from a 429, or None when Stripe sent none.
RateLimitCallback = Callable[[Optional[float]], None]
ClientFactory = Callable[[RateLimitCallback], StripeClient]


class _ListWithAllLines(Generic[_ParentT, _LineT]):
    """Listing that expands each object's embedded `lines` list.

    The list endpoint embeds at most 10 lines per object, so an object above that needs one extra
    `/lines` call. Those calls run on a small thread pool while the next page downloads. Each worker
    thread builds its own client from the factory: Stripe's RequestsClient hands a caller-supplied
    session to every thread, `requests.Session` is not documented as thread-safe, and the retrying
    client keeps per-request state. The page client comes from the same factory, so a 429 on
    either leg slows the whole pool. Objects are yielded in list order because the
    `starting_after` resume cursor is the last yielded id.
    """

    object_name: ClassVar[str]

    def __init__(
        self,
        params: Any,
        logger: FilteringBoundLogger,
        client_factory: ClientFactory,
        concurrency: int = LINE_FETCH_CONCURRENCY,
        requests_per_second: float = LINE_REQUESTS_PER_SECOND,
    ) -> None:
        self.params = params
        self.logger = logger
        self._client_factory = client_factory
        self._concurrency = concurrency
        self._pacer = RequestPacer(requests_per_second)
        self._thread_clients = threading.local()

    def _list_page(self, client: StripeClient) -> ListObject[_ParentT]:
        raise NotImplementedError

    def _list_lines(self, client: StripeClient, object_id: str) -> ListObject[_LineT]:
        raise NotImplementedError

    def _attach_lines(self, obj: _ParentT, lines: list[_LineT]) -> None:
        raise NotImplementedError

    def auto_paging_iter(self) -> Iterator[_ParentT]:
        page_client = self._client_factory(self._pacer.throttled)
        page = self._list_page(page_client)

        total_line_calls = 0
        object_count = 0
        # The next-page fetch is submitted first, so the extra worker picks it up at once and the
        # line calls fill the others.
        pool = ThreadPoolExecutor(
            max_workers=self._concurrency + 1, thread_name_prefix=f"stripe-{self.object_name.replace(' ', '-')}-lines"
        )
        try:
            while not page.is_empty:
                next_page = submit_with_context(pool, page.next_page)
                line_futures = [
                    submit_with_context(pool, self._fetch_lines, obj.id) if obj.lines.has_more and obj.id else None
                    for obj in page.data
                ]

                for obj, future in zip(page.data, line_futures):
                    if obj.lines.has_more and future is None:
                        self.logger.warning(f"Stripe {self.object_name} {obj.id} has no id")
                        continue

                    if future is not None:
                        all_lines = future.result()
                        if all_lines is not None:
                            total_line_calls += len(all_lines) // 100 + 1
                            self._attach_lines(obj, all_lines)
                            obj.lines.has_more = False
                            obj.lines.url = None  # type: ignore

                    yield obj

                    object_count += 1
                    if object_count % 10000 == 0:
                        self.logger.info(f"Stripe: processed {object_count} {self.object_name}s")

                page = next_page.result()
        finally:
            # The consumer may close the generator early; never block on requests still in flight.
            pool.shutdown(wait=False, cancel_futures=True)

        self.logger.debug(f"Stripe: made {total_line_calls} calls for {self.object_name} line items")

    def _fetch_lines(self, object_id: str) -> Optional[list[_LineT]]:
        self._pacer.wait_turn()
        try:
            return list(self._list_lines(self._thread_client(), object_id).auto_paging_iter())
        except stripe_lib.InvalidRequestError as e:
            if getattr(e, "code", None) != "resource_missing":
                raise
            self.logger.debug(f"Stripe: {self.object_name} {object_id} no longer exists, yielding with partial lines")
            return None

    def _thread_client(self) -> StripeClient:
        client: Optional[StripeClient] = getattr(self._thread_clients, "client", None)
        if client is None:
            client = self._client_factory(self._pacer.throttled)
            self._thread_clients.client = client
        return client


class InvoiceListWithAllLines(_ListWithAllLines[Invoice, InvoiceLineItem]):
    object_name = "invoice"

    def _list_page(self, client: StripeClient) -> ListObject[Invoice]:
        return client.invoices.list(params=self.params)

    def _list_lines(self, client: StripeClient, object_id: str) -> ListObject[InvoiceLineItem]:
        return client.invoices.line_items.list(invoice=object_id, params={"limit": 100})

    def _attach_lines(self, obj: Invoice, lines: list[InvoiceLineItem]) -> None:
        obj.lines.data = lines


class CreditNoteListWithAllLines(_ListWithAllLines[CreditNote, CreditNoteLineItem]):
    object_name = "credit note"

    def _list_page(self, client: StripeClient) -> ListObject[CreditNote]:
        return client.credit_notes.list(params=self.params)

    def _list_lines(self, client: StripeClient, object_id: str) -> ListObject[CreditNoteLineItem]:
        return client.credit_notes.line_items.list(credit_note=object_id, params={"limit": 100})

    def _attach_lines(self, obj: CreditNote, lines: list[CreditNoteLineItem]) -> None:
        obj.lines.data = lines
