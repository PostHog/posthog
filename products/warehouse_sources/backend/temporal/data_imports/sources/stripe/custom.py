import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, ParamSpec, TypeVar

import stripe as stripe_lib
from stripe import Invoice, InvoiceLineItem, InvoiceService, ListObject, StripeClient
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

# Receives the Retry-After seconds from a 429, or None when Stripe sent none.
RateLimitCallback = Callable[[Optional[float]], None]
ClientFactory = Callable[[RateLimitCallback], StripeClient]


class InvoiceListWithAllLines:
    """Invoice listing that expands each invoice's line items.

    The list endpoint embeds at most 10 lines per invoice, so an invoice above that needs one extra
    `/lines` call. Those calls run on a small thread pool while the next page downloads. Each worker
    thread builds its own client from the factory: Stripe's RequestsClient hands a caller-supplied
    session to every thread, `requests.Session` is not documented as thread-safe, and the retrying
    client keeps per-request state. The page client comes from the same factory, so a 429 on
    either leg slows the whole pool. Invoices are yielded in list order because the
    `starting_after` resume cursor is the last yielded id.
    """

    def __init__(
        self,
        params: InvoiceService.ListParams,
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

    def auto_paging_iter(self) -> Iterator[Invoice]:
        page_client = self._client_factory(self._pacer.throttled)
        page: ListObject[Invoice] = page_client.invoices.list(params=self.params)

        total_line_calls = 0
        invoice_count = 0
        # The next-page fetch is submitted first, so the extra worker picks it up at once and the
        # line calls fill the others.
        pool = ThreadPoolExecutor(max_workers=self._concurrency + 1, thread_name_prefix="stripe-invoice-lines")
        try:
            while not page.is_empty:
                next_page = submit_with_context(pool, page.next_page)
                line_futures = [
                    submit_with_context(pool, self._fetch_lines, invoice.id)
                    if invoice.lines.has_more and invoice.id
                    else None
                    for invoice in page.data
                ]

                for invoice, future in zip(page.data, line_futures):
                    if invoice.lines.has_more and future is None:
                        self.logger.warning(f"Invoice {invoice.id} has no id")
                        continue

                    if future is not None:
                        all_lines = future.result()
                        if all_lines is not None:
                            total_line_calls += len(all_lines) // 100 + 1
                            invoice.lines.data = all_lines
                            invoice.lines.has_more = False
                            invoice.lines.url = None  # type: ignore

                    yield invoice

                    invoice_count += 1
                    if invoice_count % 10000 == 0:
                        self.logger.info(f"Stripe: processed {invoice_count} invoices")

                page = next_page.result()
        finally:
            # The consumer may close the generator early; never block on requests still in flight.
            pool.shutdown(wait=False, cancel_futures=True)

        self.logger.debug(f"Stripe: made {total_line_calls} calls for invoice line items")

    def _fetch_lines(self, invoice_id: str) -> Optional[list[InvoiceLineItem]]:
        self._pacer.wait_turn()
        try:
            line_items = self._thread_client().invoices.line_items.list(invoice=invoice_id, params={"limit": 100})
            return list(line_items.auto_paging_iter())
        except stripe_lib.InvalidRequestError as e:
            if getattr(e, "code", None) != "resource_missing":
                raise
            self.logger.debug(f"Stripe: invoice {invoice_id} no longer exists, yielding with partial lines")
            return None

    def _thread_client(self) -> StripeClient:
        client: Optional[StripeClient] = getattr(self._thread_clients, "client", None)
        if client is None:
            client = self._client_factory(self._pacer.throttled)
            self._thread_clients.client = client
        return client
