# TrustRadius API inventory

The source uses the documented `https://api.trustradius.com/v1` server.
The specification label is `1.1`, but the version sent in requests is `v1`.

Official references:

- [API reference](https://apidocs.trustradius.com/docs/public-api/YXBpOjUxMzgzNjA-trust-radius-api)
- [Vendor OpenAPI export](https://stoplight.io/api/v1/projects/trustradius/public-api/nodes/reference/api.oas3.yml?fromExportButton=true&snapshotType=http_service)

| Table                      | GET path                              | Response         | Key                                                       | Sync                                  |
| -------------------------- | ------------------------------------- | ---------------- | --------------------------------------------------------- | ------------------------------------- |
| products                   | `/product-ids`                        | Array            | `_id`                                                     | Full refresh                          |
| product_scores             | `/product-scores`                     | `products` array | `id`                                                      | Full refresh                          |
| trustquotes                | `/trustquotes`                        | Array            | `id`                                                      | Full refresh                          |
| tags                       | `/tags`                               | Array            | `id`                                                      | Full refresh                          |
| traffic_products           | `/reports/traffic/products`           | Array            | `date`, `productId`, `categoryId`                         | Full refresh or incremental on `date` |
| traffic_pages              | `/reports/traffic/pages`              | Array            | `date`, `productId`, `url`                                | Full refresh or incremental on `date` |
| trustquotes_web_pages      | `/reports/syndication/tqw/pages`      | Array            | `date`, `productId`, `widgetId`, `domain`, `page`, `link` | Full refresh or incremental on `date` |
| visitor_insights_companies | `/reports/visitor-insights/companies` | Array            | `date`, `productId`, `companyName`                        | Full refresh or incremental on `date` |
| visitor_insights_pages     | `/reports/visitor-insights/pages`     | Array            | `date`, `productId`, `companyName`, `url`                 | Full refresh or incremental on `date` |
| intent                     | `/intent`                             | `accounts` array | `id`, `date`                                              | Full refresh or incremental on `date` |

The first four endpoints have no documented pagination parameters.
The source makes one request per table and does not send a record limit.
TrustQuotes includes anonymous quotes through the documented `include-anonymous` parameter.
Its `created` field provides a stable partition key.

TrustQuotes accepts date filters, but the specification does not identify the filtered field or guarantee response order.
The source therefore offers full refresh for this table.
The other three endpoints have no documented time filters.

The product list covers published products under the vendor profile.
Product scores cover products licensed for that API.
The API key and license control access to quotes and tags.
The security definition directs customers to their Client Success Manager for an API key.

The specification has no `/reviews` endpoint.

The two traffic reports and the two visitor insights reports send `group=day`, a `start-date` and an `end-date`, and page with `skip` and `limit`.
They sort by the primary key fields, so the `skip` pages stay stable.
A page shorter than the limit ends the walk.
The traffic reports require product identifiers, so the source reads `/product-ids` first and sends them in groups of 50.

The TrustQuotes for Web report documents no `skip` or `limit`, and it groups days with `date-group`.
The source therefore sends `date-group=day` and reads the range one day per request, so each response stays small.
The specification calls `end-date` inclusive, but the intent API treats it as exclusive.
Each request ends on the day the next one starts, and the source drops rows dated outside the requested day, so neither reading loses or repeats a day.
The specification requires `date`, so a row without a readable date is dropped too.
Its `domain`, `page` and `link` fields are optional in the specification.
All three fields are in the key, and the source writes an empty string for a missing one, so every destination can match the key.
The visitor insights reports accept no product filter from the source, so they cover every licensed product.
The specification tags both visitor insights operations as Legacy, and they need the matching license.
For all report tables, a full refresh and the first incremental run read the last 365 days, because the specification documents no retention.
An incremental run starts at the stored date, minus a default lookback of two days, because recent days can change.

Intent data covers at most the 45 days before today.
The `more` flag signals more data for the range, but no continuation request is documented.
The source therefore requests one full day at a time, from 44 days ago to yesterday, and logs a warning when `more` is true.
Each row is one account on one day, with the `date` of the request added.
A full refresh keeps only the days the API still serves, so incremental sync keeps the history.

`/accounts/{account_id}` has no table yet.

On 2026-10-05, requests without credentials and with an invented invalid key returned HTTP 401.
Successful responses were verified against the official specification and mocked tests.
No licensed account was available for a live sync.
The specification does not state a default quote limit or guarantee unrestricted historical coverage.
