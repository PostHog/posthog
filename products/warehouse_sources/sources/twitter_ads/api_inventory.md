# X Ads API endpoint inventory

These endpoints use the [X Ads API v12 campaign management reference](https://docs.x.com/x-ads-api/campaign-management/reference.md).
All requests use [OAuth 1.0a user authentication](https://docs.x.com/x-ads-api/fundamentals/making-authenticated-requests.md).
The app needs [Standard Access](https://docs.x.com/x-ads-api/fundamentals/accessing-ads-accounts.md#levels-of-access), and the authorized user needs read access to the selected ad account.

| Table                | GET path                                       | One row represents                         | Primary key | Pagination and filters                                                                                 |
| -------------------- | ---------------------------------------------- | ------------------------------------------ | ----------- | ------------------------------------------------------------------------------------------------------ |
| `accounts`           | `/12/accounts`                                 | One ad account                             | `id`        | Filter by the selected `account_ids` value. Follow `next_cursor`.                                      |
| `promoted_accounts`  | `/12/accounts/{account_id}/promoted_accounts`  | One promoted account linked to a line item | `id`        | Follow `next_cursor` for the selected ad account.                                                      |
| `targeting_criteria` | `/12/accounts/{account_id}/targeting_criteria` | One targeting criterion for a line item    | `id`        | Fetch line items in groups of up to 200. Send `line_item_ids` and follow `next_cursor` for each group. |

All three endpoints return `updated_at`, but none documents a timestamp filter. The source uses full refresh for each table.

The source does not import `/12/accounts/{account_id}/account_history`. That beta endpoint requires allowlisting and an `entity_id` for each request.
