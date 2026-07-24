# custom functions for stripe sources
import stripe as stripe_lib
from stripe import InvoiceService, StripeClient
from structlog.types import FilteringBoundLogger


class InvoiceListWithAllLines:
    # Invoices have a line field that is a paginated list. This list needs to be expanded for all lines to be included

    def __init__(self, client: StripeClient, params: InvoiceService.ListParams, logger: FilteringBoundLogger):
        self.client = client
        self.params = params
        self.logger = logger

    def auto_paging_iter(self):
        invoices = self.client.invoices.list(params=self.params)

        total_line_calls = 0
        invoice_count = 0
        for invoice in invoices.auto_paging_iter():
            # if there are more lines, custom iterate over the lines
            if invoice.lines.has_more:
                if not invoice.id:
                    self.logger.warning(f"Invoice {invoice.id} has no id")
                    continue

                all_lines = []
                try:
                    line_items = self.client.invoices.line_items.list(invoice=invoice.id, params={"limit": 100})
                    for line in line_items.auto_paging_iter():
                        all_lines.append(line)
                except stripe_lib.InvalidRequestError as e:
                    # The invoice was deleted between listing it and fetching its lines (e.g. a
                    # draft invoice removed mid-sync). Yield it with whatever lines it already had
                    # from the initial listing rather than failing the whole import.
                    if getattr(e, "code", None) != "resource_missing":
                        raise
                    self.logger.debug(f"Stripe: invoice {invoice.id} no longer exists, yielding with partial lines")
                else:
                    # number of api pages made. Each page is 100
                    total_line_calls += len(all_lines) // 100 + 1

                    invoice.lines.data = all_lines
                    invoice.lines.has_more = False
                    # type is string but stripe api error message says None is the right way to set this
                    invoice.lines.url = None  # type: ignore

            yield invoice

            # status update every 10000 invoices
            invoice_count += 1
            if invoice_count % 10000 == 0:
                self.logger.info(f"Stripe: processed {invoice_count} invoices")

        self.logger.debug(f"Stripe: made {total_line_calls} calls for invoice line items")
