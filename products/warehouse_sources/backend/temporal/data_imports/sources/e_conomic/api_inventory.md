# Visma e-conomic API inventory

Reference notes for the `e_conomic` source. All behavior below was verified with `curl` against the
live API (`https://restapi.e-conomic.com`) using e-conomic's public demo agreement
(`X-AppSecretToken: demo`, `X-AgreementGrantToken: demo`).

## Auth

- Two custom headers: `X-AppSecretToken` (per-app developer secret) and `X-AgreementGrantToken`
  (per-agreement grant issued when a user installs the app). Not OAuth.
- No per-resource scopes — a valid grant token reads the whole agreement.
- Bad app-secret **or** grant token → `401 Unauthorized` (the API does not distinguish the two, and
  there is no `403` for missing scope).
- Cheap validation probe: `GET /self` (returns agreement/company metadata).

## Response shape & pagination

- List endpoints return `{"collection": [...], "pagination": {...}, "self": "..."}`.
- Offset pagination: `pagesize` (max **1000**) + `skippages`. Responses carry HATEOAS links
  `pagination.firstPage` / `nextPage` / `lastPage`. We follow `nextPage` until absent.
- `nextPage` preserves `pagesize`, `sort` and `filter` (URL-encoded), so resuming a sync is just
  "GET the saved `nextPage` URL".

## Incremental filtering

- Server-side filtering via `filter=<field>$<op>:<value>` with Mongo-style operators (`$gte`, `$gt`, …).
- Confirmed the filter is genuinely applied (future-date cutoff → 0 results; past-date → all results).
- `lastUpdated` filtering coverage **varies per endpoint** — present on customers, products and draft
  invoices; absent on suppliers and the reference tables.
- **Sort enums vary per endpoint** and are enforced (`400` on an unsupported field). An incremental
  field is only usable when the endpoint can also `sort` ascending by it (so rows arrive in watermark
  order). `sort=lastUpdated` works on customers/products but **`400`s on draft invoices**.

## Endpoint matrix

| Schema                       | Path                                          | Primary key                                        | Sort                             | Incremental                        | Notes                                                          |
| ---------------------------- | --------------------------------------------- | -------------------------------------------------- | -------------------------------- | ---------------------------------- | -------------------------------------------------------------- |
| `customers`                  | `/customers`                                  | `customerNumber`                                   | `lastUpdated`                    | ✅ `lastUpdated` (DateTime)        |                                                                |
| `customer_groups`            | `/customer-groups`                            | `customerGroupNumber`                              | `customerGroupNumber`            | full refresh                       |                                                                |
| `products`                   | `/products`                                   | `productNumber`                                    | `lastUpdated`                    | ✅ `lastUpdated` (DateTime)        |                                                                |
| `product_groups`             | `/product-groups`                             | `productGroupNumber`                               | `productGroupNumber`             | full refresh                       |                                                                |
| `suppliers`                  | `/suppliers`                                  | `supplierNumber`                                   | `supplierNumber`                 | full refresh                       | no `lastUpdated` field; filter on it errors                    |
| `supplier_groups`            | `/supplier-groups`                            | `supplierGroupNumber`                              | `supplierGroupNumber`            | full refresh                       |                                                                |
| `accounts`                   | `/accounts`                                   | `accountNumber`                                    | `accountNumber`                  | full refresh                       | chart of accounts                                              |
| `accounting_years`           | `/accounting-years`                           | `year`                                             | `year`                           | full refresh                       |                                                                |
| `journals`                   | `/journals`                                   | `journalNumber`                                    | `journalNumber`                  | full refresh                       |                                                                |
| `currencies`                 | `/currencies`                                 | `code`                                             | `code`                           | full refresh                       |                                                                |
| `payment_terms`              | `/payment-terms`                              | `paymentTermsNumber`                               | _(none)_                         | full refresh                       | `sort=paymentTermsNumber` → 400; tiny single-page table        |
| `departments`                | `/departments`                                | `departmentNumber`                                 | `departmentNumber`               | full refresh                       |                                                                |
| `departmental_distributions` | `/departmental-distributions`                 | `departmentalDistributionNumber`                   | `departmentalDistributionNumber` | full refresh                       |                                                                |
| `units`                      | `/units`                                      | `unitNumber`                                       | `unitNumber`                     | full refresh                       |                                                                |
| `vat_zones`                  | `/vat-zones`                                  | `vatZoneNumber`                                    | `vatZoneNumber`                  | full refresh                       |                                                                |
| `vat_types`                  | `/vat-types`                                  | `vatTypeNumber`                                    | _(none)_                         | full refresh                       | `sort` is accepted but ignored                                 |
| `vat_accounts`               | `/vat-accounts`                               | `vatCode`                                          | _(none)_                         | full refresh                       | `sort` is accepted but ignored                                 |
| `payment_types`              | `/payment-types`                              | `paymentTypeNumber`                                | _(none)_                         | full refresh                       | `sort` is accepted but ignored                                 |
| `employees`                  | `/employees`                                  | `employeeNumber`                                   | `employeeNumber`                 | full refresh                       |                                                                |
| `invoices_booked`            | `/invoices/booked`                            | `bookedInvoiceNumber`                              | `bookedInvoiceNumber`            | ✅ `bookedInvoiceNumber` (Integer) | immutable; partition by stable `date`                          |
| `invoices_drafts`            | `/invoices/drafts`                            | `draftInvoiceNumber`                               | `draftInvoiceNumber`             | full refresh                       | has `lastUpdated` filter, but `sort=lastUpdated` → 400         |
| `orders_drafts`              | `/orders/drafts`                              | `orderNumber`                                      | `orderNumber`                    | full refresh                       | rows leave the table when the order is sent                    |
| `orders_sent`                | `/orders/sent`                                | `orderNumber`                                      | `orderNumber`                    | full refresh                       | rows leave the table when the order is archived                |
| `orders_archived`            | `/orders/archived`                            | `orderNumber`                                      | `orderNumber`                    | full refresh                       | no `lastUpdated`; partition by `date`                          |
| `accounting_year_entries`    | `/accounting-years/{year}/entries`            | `accountingYear`, `entryNumber`                    | `entryNumber`                    | full refresh                       | fan-out over `accounting_years` via each year's `entries` link |
| `journal_entries`            | `/journals/{n}/entries`                       | `journalNumber`, `journalEntryNumber`              | `journalEntryNumber`             | full refresh                       | fan-out over `journals`; unbooked entries only                 |
| `journal_vouchers`           | `/journals/{n}/vouchers`                      | `journalNumber`, `accountingYear`, `voucherNumber` | _(none)_                         | full refresh                       | fan-out over `journals`; every `sort` field → 400              |
| `accounting_year_totals`     | `/accounting-years/{year}/totals`             | `accountingYear`, `accountNumber`                  | _(none)_                         | full refresh                       | fan-out over `accounting_years` via each year's `totals` link  |
| `accounting_period_totals`   | `/accounting-years/{year}/periods/{p}/totals` | `accountingYear`, `periodNumber`, `accountNumber`  | _(none)_                         | full refresh                       | two-hop fan-out: years → periods → totals                      |

## Throttling

- The API throttles and can return `429` (and transient `5xx`). Retry with backoff; honor `Retry-After`
  when present. Published rate-limit numbers are not clearly documented.

## Fan-out endpoints

- `accounting_year_entries` reads `/accounting-years/{year}/entries` once per accounting year. A year
  that spans two calendar years is named `YYYY/YYYY` but uses another form in URLs, so the path comes
  from the parent row's `entries` link. The entry number restarts with each accounting year, so the
  year is part of the primary key.
- `journal_entries` reads `/journals/{journalNumber}/entries` once per journal. These are entries that
  are not booked yet; booking moves them to the accounting-year entries.
- `journal_vouchers` reads `/journals/{journalNumber}/vouchers` once per journal. A voucher number is
  unique per journal and accounting year, so `accountingYear` is lifted out of its nested object into
  the primary key.
- `accounting_year_totals` reads each year's `totals` link. `accounting_period_totals` reads each year's
  `periods` link, then each period's `totals` link. Period numbers continue across accounting years
  (for example 25 to 36 for the third year). Both lift `account.accountNumber` into `accountNumber`.
- All are full refresh. Resume state records which parents finished and the page of the current one,
  except for `accounting_period_totals`: the framework keeps no resume state for a two-hop chain.
- `/accounts/{accountNumber}/accounting-years/{year}/entries` is not synced: it returns a per-account
  subset of `accounting_year_entries`, which already carries `account`.

## Not implemented (yet)

Other sub-resources (customer contacts, invoice lines, accounting-year vouchers, periods as a table) and the separate
sub-APIs on `apis.e-conomic.com` (subscriptions, etc.) are out of scope for now.
