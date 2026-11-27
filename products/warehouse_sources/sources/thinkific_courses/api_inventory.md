# Thinkific Courses API inventory

The source uses the [Thinkific Admin API v1 OpenAPI reference](https://developers.thinkific.com/openapi/thinkific-admin-api-v1.yaml).
Paths are relative to `https://api.thinkific.com/api/public/v1`.

The connector sends `X-Auth-API-Key` and `X-Auth-Subdomain` for both parent and child requests.
The API-key connection does not use OAuth scopes.
The OpenAPI reference lists no operation-specific scope for these endpoints.

| Table                | Endpoint                          | Row grain                                  | Primary key           | Pagination      | Incremental candidate                   |
| -------------------- | --------------------------------- | ------------------------------------------ | --------------------- | --------------- | --------------------------------------- |
| `bundle_courses`     | `GET /bundles/{id}/courses`       | One course in one bundle                   | `bundle_id`, `id`     | Page number     | None. Full refresh.                     |
| `bundle_enrollments` | `GET /bundles/{id}/enrollments`   | One enrollment in one bundle               | `bundle_id`, `id`     | Page number     | `updated_at` via `query[updated_after]` |
| `group_analysts`     | `GET /groups/{group_id}/analysts` | One analyst assignment in one group        | `group_id`, `user_id` | Single response | None. Full refresh.                     |
| `related_products`   | `GET /products/{id}/related`      | One related product for one parent product | `product_id`, `id`    | Page number     | None. Full refresh.                     |

- `GET /products` supplies both sets of product parents. Bundle requests use the `productable_id` of products with `productable_type=Bundle`. Related-product requests use the parent product's `id`.
- `GET /groups` supplies group IDs. The connector expands the `group_analysts` array into one row per user ID.
- Paginated responses contain `items` and `meta.pagination.total_pages`. Requests use `page` and `limit`. The connector fails the sync if a child listing still has more pages after 1,000 pages for one parent.
- Bundle enrollment filters use UTC dates. The connector sends the day before the saved `updated_at` date so the exclusive `updated_after` filter includes the saved date.
