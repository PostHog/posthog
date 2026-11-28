# Salesflare API inventory

The [Salesflare API specification](https://api.salesflare.com/openapi.json) lists these endpoints. The requests use a Salesflare API key as a bearer token. The specification does not list endpoint-specific scopes.

| Endpoint                              | Row                                                                 | Pagination                                             | Warehouse key      | Incremental sync                                                                                         |
| ------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------ | ------------------ | -------------------------------------------------------------------------------------------------------- |
| `GET /persons`                        | One person                                                          | No pagination parameters                               | `id`               | Full refresh. No time filter.                                                                            |
| `GET /customfields/{itemClass}`       | One custom field definition for an account, contact, or opportunity | One request per record type. No pagination parameters. | `item_class`, `id` | Full refresh. No time filter.                                                                            |
| `GET /accounts/{account_id}/feed`     | One activity in an account                                          | `before`, `after`, `limit`                             | Not documented     | Not imported. The specification does not explain how to page through activities with the same timestamp. |
| `GET /accounts/{account_id}/messages` | One message in an account                                           | `before`, `after`, `limit`                             | Not documented     | Not imported. The specification does not explain how to page through messages with the same timestamp.   |

Requests without an API key returned HTTP 401. The response shapes could not be verified with a live request.
