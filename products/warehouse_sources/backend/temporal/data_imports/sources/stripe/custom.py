import time
import threading
import contextvars
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Optional, ParamSpec, TypeVar

import stripe as stripe_lib
from stripe import Invoice, InvoiceLineItem, InvoiceService, ListObject, StripeClient
from structlog.types import FilteringBoundLogger

# Stripe's test-mode read limit is 25 requests/s and the live-mode limit is 100. Five workers stay
# under both, and the page fetch is the longer leg of an iteration, so more would not shorten a sweep.
LINE_FETCH_CONCURRENCY = 5
# Fast responses could still let five workers exceed the test-mode limit, so request starts are paced
# independently of the worker count. The limit is per account, shared with every other caller.
LINE_REQUESTS_PER_SECOND = 20.0
# How long a 429 keeps the pool at a reduced rate when Stripe sends no Retry-After.
RATE_LIMIT_HOLD_SECONDS = 30.0

_P = ParamSpec("_P")
_T = TypeVar("_T")

# Receives the Retry-After seconds from a 429, or None when Stripe sent none.
RateLimitCallback = Callable[[Optional[float]], None]
ClientFactory = Callable[[RateLimitCallback], StripeClient]


class _RequestPacer:
    """Spaces request starts across threads and slows the whole pool after a rate limit.

    Every worker calls wait_turn() before a request, so the pool never starts more than
    `per_second` requests in any second. A 429 halves the rate for the hold window and, when
    Stripe sends Retry-After, holds every worker until it passes, including workers already
    waiting for a slot. Each quiet window after that doubles the rate back until the base rate
    is restored.
    """

    def __init__(
        self,
        per_second: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_interval = 1.0 / per_second
        self._interval = self._base_interval
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_start = 0.0
        self._hold_until = 0.0
        self._recover_at: Optional[float] = None

    def wait_turn(self) -> None:
        start = self._reserve_slot()
        while True:
            delay = start - self._clock()
            if delay > 0:
                self._sleep(delay)
            with self._lock:
                if self._hold_until <= start:
                    return
            # A throttle arrived during the sleep and its hold covers this slot: take a later one.
            start = self._reserve_slot()

    def _reserve_slot(self) -> float:
        with self._lock:
            now = self._clock()
            if self._recover_at is not None and now >= self._recover_at:
                self._interval = max(self._interval / 2, self._base_interval)
                self._recover_at = None if self._interval == self._base_interval else now + RATE_LIMIT_HOLD_SECONDS
            start = max(now, self._next_start)
            self._next_start = start + self._interval
            return start

    def throttled(self, retry_after: Optional[float]) -> None:
        with self._lock:
            now = self._clock()
            if now < self._hold_until:
                # Requests already in flight when the first 429 landed report the same throttle.
                return
            hold = retry_after if retry_after is not None and retry_after > 0 else RATE_LIMIT_HOLD_SECONDS
            self._interval = min(self._interval * 2, self._base_interval * 16)
            if retry_after is not None and retry_after > 0:
                self._hold_until = now + retry_after
                self._next_start = max(self._next_start, self._hold_until)
            self._recover_at = now + hold


def _submit(pool: ThreadPoolExecutor, fn: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> Future[_T]:
    """Run `fn` on the pool inside a copy of the caller's context.

    Pool threads start with an empty context, which would strip the team and job labels that the
    HTTP observer and structlog read from contextvars.
    """
    ctx = contextvars.copy_context()
    return pool.submit(lambda: ctx.run(fn, *args, **kwargs))


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
        self._pacer = _RequestPacer(requests_per_second)
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
