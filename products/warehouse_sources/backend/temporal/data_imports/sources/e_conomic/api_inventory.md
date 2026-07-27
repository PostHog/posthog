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

| Schema                       | Path                          | Primary key                      | Sort                             | Incremental                        | Notes                                                   |
| ---------------------------- | ----------------------------- | -------------------------------- | -------------------------------- | ---------------------------------- | ------------------------------------------------------- |
| `customers`                  | `/customers`                  | `customerNumber`                 | `lastUpdated`                    | ✅ `lastUpdated` (DateTime)        |                                                         |
| `customer_groups`            | `/customer-groups`            | `customerGroupNumber`            | `customerGroupNumber`            | full refresh                       |                                                         |
| `products`                   | `/products`                   | `productNumber`                  | `lastUpdated`                    | ✅ `lastUpdated` (DateTime)        |                                                         |
| `product_groups`             | `/product-groups`             | `productGroupNumber`             | `productGroupNumber`             | full refresh                       |                                                         |
| `suppliers`                  | `/suppliers`                  | `supplierNumber`                 | `supplierNumber`                 | full refresh                       | no `lastUpdated` field; filter on it errors             |
| `supplier_groups`            | `/supplier-groups`            | `supplierGroupNumber`            | `supplierGroupNumber`            | full refresh                       |                                                         |
| `accounts`                   | `/accounts`                   | `accountNumber`                  | `accountNumber`                  | full refresh                       | chart of accounts                                       |
| `accounting_years`           | `/accounting-years`           | `year`                           | `year`                           | full refresh                       |                                                         |
| `journals`                   | `/journals`                   | `journalNumber`                  | `journalNumber`                  | full refresh                       |                                                         |
| `currencies`                 | `/currencies`                 | `code`                           | `code`                           | full refresh                       |                                                         |
| `payment_terms`              | `/payment-terms`              | `paymentTermsNumber`             | _(none)_                         | full refresh                       | `sort=paymentTermsNumber` → 400; tiny single-page table |
| `departments`                | `/departments`                | `departmentNumber`               | `departmentNumber`               | full refresh                       |                                                         |
| `departmental_distributions` | `/departmental-distributions` | `departmentalDistributionNumber` | `departmentalDistributionNumber` | full refresh                       |                                                         |
| `units`                      | `/units`                      | `unitNumber`                     | `unitNumber`                     | full refresh                       |                                                         |
| `vat_zones`                  | `/vat-zones`                  | `vatZoneNumber`                  | `vatZoneNumber`                  | full refresh                       |                                                         |
| `employees`                  | `/employees`                  | `employeeNumber`                 | `employeeNumber`                 | full refresh                       |                                                         |
| `invoices_booked`            | `/invoices/booked`            | `bookedInvoiceNumber`            | `bookedInvoiceNumber`            | ✅ `bookedInvoiceNumber` (Integer) | immutable; partition by stable `date`                   |
| `invoices_drafts`            | `/invoices/drafts`            | `draftInvoiceNumber`             | `draftInvoiceNumber`             | full refresh                       | has `lastUpdated` filter, but `sort=lastUpdated` → 400  |

## Throttling

- The API throttles and can return `429` (and transient `5xx`). Retry with backoff; honor `Retry-After`
  when present. Published rate-limit numbers are not clearly documented.

## Not implemented (yet)

Sub-resources/fan-out (customer contacts, invoice lines, account entries per accounting year) and the
separate sub-APIs on `apis.e-conomic.com` (subscriptions, etc.) are out of scope for the initial source.
Account entries in particular require a per-accounting-year fan-out (`/accounting-years/{year}/entries`).
