# Amplemarket endpoint inventory

This inventory covers the personas, territories, and contact sequences routes in the [Amplemarket v1 API reference](https://api.amplemarket.com/api-docs/v1/swagger.yaml).
All three routes use an API key as a bearer token. The API reference lists no additional scopes for these routes.

| Route                          | Row grain     | Row key                       | Pagination                                 | Sync decision                      |
| ------------------------------ | ------------- | ----------------------------- | ------------------------------------------ | ---------------------------------- |
| `GET /personas`                | One persona   | `id` (UUID)                   | `_links.next.href`; default and maximum 20 | Full refresh. No timestamp filter. |
| `GET /territories`             | One territory | `id` (UUID)                   | `_links.next.href`; default and maximum 20 | Full refresh. No timestamp filter. |
| `GET /contacts/{id}/sequences` | One lead      | No documented unique lead key | `_links.next.href`; default 10, maximum 50 | Not synced. No timestamp filter.   |

The contact sequences route returns a sequence ID, not a lead ID. Reading this route also requires listing contacts for each account.
