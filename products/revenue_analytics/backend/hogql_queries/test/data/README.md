# Test data for revenue analytics

CSV files simulating Stripe data warehouse tables,
used by integration tests across revenue analytics and the persons/groups join tests.

## Customers (`stripe_customers.csv`)

6 customers across 3 countries, created in early January 2023.

| Customer | Name           | Email                    | Country | `posthog_person_distinct_id` | Resolution path                                                  |
| -------- | -------------- | ------------------------ | ------- | ---------------------------- | ---------------------------------------------------------------- |
| `cus_1`  | John Doe       | john.doe@example.com     | US      | `person_cus_1` (on customer) | Direct on customer                                               |
| `cus_2`  | Jane Doe       | jane.doe@example.com     | US      | (none)                       | Resolved from subscription `sub_2`                               |
| `cus_3`  | John Smith     | john.smith@example.com   | CA      | (none)                       | Resolved from charge `ch_3`                                      |
| `cus_4`  | Jane Smith     | jane.smith@example.com   | CA      | (none)                       | No distinct ID anywhere                                          |
| `cus_5`  | John Doe Jr    | john.doejr@example.com   | UK      | (none)                       | Resolved from charge `ch_15` (fresher than subscription `sub_5`) |
| `cus_6`  | John Doe Jr Jr | john.doejrjr@example.com | UK      | (none)                       | No distinct ID anywhere                                          |

All customers have a legacy `id` key in their metadata (e.g. `cus_1_metadata`),
used by the `test_get_revenue_for_schema_source_for_metadata_join` test in `test_persons_revenue_analytics.py`.

## Subscriptions (`stripe_subscriptions.csv`)

One subscription per customer. All have status `active`.
The first two are roughly annual (ending January 2026), the rest are ~3 months (ending May 2025).

| Subscription | Customer | Product  | Created    | Ends       | `posthog_person_distinct_id` |
| ------------ | -------- | -------- | ---------- | ---------- | ---------------------------- |
| `sub_1`      | `cus_1`  | `prod_1` | 2025-01-23 | 2026-01-23 | (none)                       |
| `sub_2`      | `cus_2`  | `prod_2` | 2025-01-23 | 2026-01-23 | `person_cus_2`               |
| `sub_3`      | `cus_3`  | `prod_3` | 2025-01-23 | 2025-06-23 | (none)                       |
| `sub_4`      | `cus_4`  | `prod_4` | 2025-02-23 | 2025-05-23 | (none)                       |
| `sub_5`      | `cus_5`  | `prod_5` | 2025-02-23 | 2025-05-23 | `person_cus_5_from_sub`      |
| `sub_6`      | `cus_6`  | `prod_6` | 2025-02-23 | 2025-05-23 | (none)                       |

For `cus_5`, the subscription (`sub_5`, February 2025) is **older** than the charge (`ch_15`, March 2025),
so the resolution should prefer the charge's value.

## Charges (`stripe_charges.csv`)

22 charges spanning January through April 2025, across 4 currencies (USD, EUR, GBP, JPY).

### By status

- **19 succeeded** — normal payments
- **1 failed** — `ch_5` (cus_5, 7500 EUR): `insufficient_funds`
- **2 pending** — `ch_11` (cus_1, 9000 USD, no invoice), `ch_18` (cus_3, 100 USD)

### Refunds

- `ch_4` (cus_4): full refund — 20,000 of 20,000 USD
- `ch_6` (cus_1): partial refund — 2,500 of 12,500 GBP
- `ch_12` (cus_2): full refund — 22,000 of 22,000 EUR

### Per-customer summary

| Customer | Charges | Currencies    | Gross   | Refunded | Notable                                                                        |
| -------- | ------- | ------------- | ------- | -------- | ------------------------------------------------------------------------------ |
| `cus_1`  | 6       | USD, GBP, EUR | 96,500  | 2,500    | 1 pending (`ch_11`), 1 partial refund (`ch_6`), 1 invoiceless charge (`ch_22`) |
| `cus_2`  | 4       | EUR, USD, GBP | 85,000  | 22,000   | 1 full refund (`ch_12`)                                                        |
| `cus_3`  | 4       | GBP, JPY, USD | 340,100 | 0        | 1 very large charge (`ch_13`: 334,500 USD), 1 pending (`ch_18`)                |
| `cus_4`  | 4       | USD, EUR      | 70,000  | 20,000   | 1 full refund (`ch_4`)                                                         |
| `cus_5`  | 4       | EUR, GBP, USD | 52,500  | 0        | 1 failed charge (`ch_5`)                                                       |
| `cus_6`  | 0       | —             | 0       | 0        | No charges at all                                                              |

### Person distinct ID on charges

| Charge  | Customer | `posthog_person_distinct_id` | Created    |
| ------- | -------- | ---------------------------- | ---------- |
| `ch_3`  | `cus_3`  | `person_cus_3`               | 2025-01-31 |
| `ch_15` | `cus_5`  | `person_cus_5_from_charge`   | 2025-03-03 |

## Invoices (`stripe_invoices.csv`)

20 invoices, all paid, all `billing_reason=subscription_cycle`.
Created monthly on the 23rd from January through May 2025.

| Customer | Invoice count | With subscription                      | Without subscription     |
| -------- | ------------- | -------------------------------------- | ------------------------ |
| `cus_1`  | 3             | `in_1`, `in_9`, `in_17` (all `sub_1`)  | —                        |
| `cus_2`  | 6             | `in_2`, `in_10`, `in_18` (`sub_2`)     | `in_3`, `in_11`, `in_19` |
| `cus_3`  | 3             | `in_4`, `in_12`, `in_20` (all `sub_3`) | —                        |
| `cus_4`  | 2             | `in_5`, `in_13` (both `sub_4`)         | —                        |
| `cus_5`  | 4             | `in_6`, `in_14` (`sub_5`)              | `in_7`, `in_15`          |
| `cus_6`  | 2             | `in_8`, `in_16` (both `sub_6`)         | —                        |

`cus_2` and `cus_5` have invoices without subscription links — edge case for testing invoices not tied to recurring billing.
No invoices have `posthog_person_distinct_id` in metadata.

## Products (`stripe_products.csv`)

9 service-type products (`prod_1` through `prod_9`), all active.
Products 1–6 are referenced by subscriptions. Products 7–9 are unused (available for future tests).

## Column definitions (`structure.py`)

`STRIPE_*_COLUMNS` dicts define ClickHouse column types for each table.
Used by `create_data_warehouse_table_from_csv` to set up test tables.
Also defines `REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT` — the default purchase event config
used by event-based revenue tests (event name `purchase`, revenue property `revenue`,
currency property `currency`, 45-day subscription dropoff).

## Expected revenue per customer

These values appear in test assertions across multiple test files (base currency GBP):

| Customer | Revenue (GBP) | Source                        |
| -------- | ------------- | ----------------------------- |
| `cus_1`  | 517.71        | `test_with_data_group_by_all` |
| `cus_2`  | 222.61        | `test_with_data_group_by_all` |
| `cus_3`  | 1,923.37      | `test_with_data_group_by_all` |
| `cus_4`  | 170.96        | `test_with_data_group_by_all` |
| `cus_5`  | 1,379.39      | `test_with_data_group_by_all` |
| `cus_6`  | 1,337.35      | `test_with_data_group_by_all` |
