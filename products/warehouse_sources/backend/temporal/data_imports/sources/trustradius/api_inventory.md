# TrustRadius API inventory

The source uses the documented `https://api.trustradius.com/v1` server.
The specification label is `1.1`, but the version sent in requests is `v1`.

Official references:

- [API reference](https://apidocs.trustradius.com/docs/public-api/YXBpOjUxMzgzNjA-trust-radius-api)
- [Vendor OpenAPI export](https://stoplight.io/api/v1/projects/trustradius/public-api/nodes/reference/api.oas3.yml?fromExportButton=true&snapshotType=http_service)

| Table          | GET path          | Response         | Key   | Sync         |
| -------------- | ----------------- | ---------------- | ----- | ------------ |
| products       | `/product-ids`    | Array            | `_id` | Full refresh |
| product_scores | `/product-scores` | `products` array | `id`  | Full refresh |
| trustquotes    | `/trustquotes`    | Array            | `id`  | Full refresh |
| tags           | `/tags`           | Array            | `id`  | Full refresh |

These endpoints have no documented pagination parameters.
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
Traffic reports need product identifiers and have separate pagination requirements.
Intent data has a limited date range and a `more` signal without a documented continuation request.
These reports are outside this source's initial scope.

On 2026-10-05, requests without credentials and with an invented invalid key returned HTTP 401.
Successful responses were verified against the official specification and mocked tests.
No licensed account was available for a live sync.
The specification does not state a default quote limit or guarantee unrestricted historical coverage.
