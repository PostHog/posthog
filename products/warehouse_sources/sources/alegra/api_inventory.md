# Alegra v1 endpoint inventory

The source reads from `https://api.alegra.com/api/v1` with HTTP Basic authentication.
It uses the Alegra account email as the username and the API token as the password.
The REST references do not list endpoint-specific scopes for Basic authentication.

| Table                | GET path                                                                               | One row per                         | Primary and partition key | Incremental candidate                                                   |
| -------------------- | -------------------------------------------------------------------------------------- | ----------------------------------- | ------------------------- | ----------------------------------------------------------------------- |
| `income_debit_notes` | [`/income-debit-notes`](https://developer.alegra.com/reference/get_income-debit-notes) | Customer debit note                 | `id` (string)             | None. `date` and `dueDate` are exact-match filters, not change cursors. |
| `retentions`         | [`/retentions`](https://developer.alegra.com/reference/get_retentions)                 | Tax withholding definition          | `id` (string)             | None documented.                                                        |
| `currencies`         | [`/currencies`](https://developer.alegra.com/reference/get_currencies)                 | Configured currency                 | `code` (string)           | None documented.                                                        |
| `custom_fields`      | [`/custom-fields`](https://developer.alegra.com/reference/get_custom-fields)           | Custom field definition for an item | `id` (string)             | None documented.                                                        |

## Pagination

All four tables use full refresh and read a JSON array without a metadata wrapper.
The source sends `start` as a zero-based offset and `limit=30`.
It saves the offset to resume a sync and stops when a page returns fewer than 30 rows.

The REST reference documents `start` and `limit` for retentions, currencies, and custom fields.
The income debit notes REST reference omits those parameters, but [Alegra's MCP reference for the same resource](https://developer.alegra.com/reference/incomedebitnotes_income_get-debit-notes) documents both.
Live REST pagination remains unverified for all four endpoints because the API requires account credentials.
