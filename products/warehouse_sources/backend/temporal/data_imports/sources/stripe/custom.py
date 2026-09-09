import threading
import contextvars
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Optional, TypeVar

import stripe as stripe_lib
from stripe import Invoice, InvoiceLineItem, InvoiceService, ListObject, StripeClient
from structlog.types import FilteringBoundLogger

# Stripe's test-mode read limit is 25 requests/s and the live-mode limit is 100. Five workers stay
# under both, and the page fetch is the longer leg of an iteration, so more would not shorten a sweep.
LINE_FETCH_CONCURRENCY = 5

_T = TypeVar("_T")


def _submit(pool: ThreadPoolExecutor, fn: Callable[..., _T], *args: Any) -> Future[_T]:
    # Pool threads start with an empty context, which would strip the team and job labels that the
    # HTTP observer and structlog read from contextvars. Run each task inside a copy of the caller's.
    ctx = contextvars.copy_context()
    return pool.submit(lambda: ctx.run(fn, *args))


class InvoiceListWithAllLines:
    # Invoices have a line field that is a paginated list. This list needs to be expanded for all lines to be included.
    # Invoices are yielded in list order because the `starting_after` resume cursor is the last yielded id.

    def __init__(
        self,
        client: StripeClient,
        params: InvoiceService.ListParams,
        logger: FilteringBoundLogger,
        client_factory: Optional[Callable[[], StripeClient]] = None,
        concurrency: int = LINE_FETCH_CONCURRENCY,
    ):
        self.client = client
        self.params = params
        self.logger = logger
        # Stripe's RequestsClient shares a caller-supplied session across threads and its adapter pool
        # is sized for one caller, so each worker thread builds its own client from the factory.
        self._client_factory = client_factory or (lambda: client)
        self._concurrency = concurrency
        self._thread_clients = threading.local()

    def auto_paging_iter(self) -> Iterator[Invoice]:
        page: ListObject[Invoice] = self.client.invoices.list(params=self.params)

        total_line_calls = 0
        invoice_count = 0
        # One extra worker so the next-page prefetch never queues behind the line-item calls.
        pool = ThreadPoolExecutor(max_workers=self._concurrency + 1)
        try:
            while not page.is_empty:
                next_page = _submit(pool, page.next_page)
                line_futures = [
                    _submit(pool, self._fetch_lines, invoice.id) if invoice.lines.has_more and invoice.id else None
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
            client = self._client_factory()
            self._thread_clients.client = client
        return client
