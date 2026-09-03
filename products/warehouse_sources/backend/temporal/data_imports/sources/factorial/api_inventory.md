# Factorial API inventory

Source-local notes for the Factorial (HRIS) connector. See the official reference at
<https://apidoc.factorialhr.com/>.

## Connection

- **Host:** single global host `https://api.factorialhr.com` (no per-account subdomains).
- **Version:** dated path segment → base `https://api.factorialhr.com/api/<version>`. Supported labels
  `2025-04-01`, `2026-04-01`, and `2026-07-01` (default); the source's resolved pin is threaded into the
  base URL in `factorial.py`. Resources occasionally move between groups across versions, but the resource
  paths and the `{"meta": ..., "data": [...]}` envelope our reads use are identical across all three labels
  (newer versions only add/remove response fields, which the auto-inferred schema absorbs).
- **Identifier serialization:** `2026-07-01` ("Bessel") serializes every resource id as an opaque string
  instead of an integer (ids outgrew the safe 64-bit range) — in request params, responses, and webhooks.
  Our reads tolerate this without a version branch: the primary key stays the `id` column (type-agnostic,
  auto-inferred) and pagination forwards the opaque `meta.end_cursor`, never a raw record id. Pins on
  `2025-04-01` / `2026-04-01` keep integer ids.
- **Auth:** `x-api-key: <key>` header (API key). OAuth2 is also supported by Factorial but not implemented
  here — API key auth is fully supported for company/internal integrations and grants total account access.
- **Resource path shape:** `/resources/<group>/<resource>` (e.g. `/resources/employees/employees`).

## Pagination

- Cursor pagination by record id. Params: `limit` (default & max 100), `after_id` (forward), `before_id`
  (backward). Response envelope: `{"meta": {...}, "data": [...]}`.
- `meta` carries `has_next_page`, `has_previous_page`, `start_cursor`, `end_cursor`, `total`, `limit`.
- Forward paging: pass `after_id = meta.end_cursor` until `has_next_page` is false. Records come back in
  ascending id order. Implemented by `FactorialCursorPaginator`.
- No documented `sort` / `order` param; ordering is implied by the id cursor walk.

## Incremental sync

- Server-side `updated_after` is documented for only a narrow set of resources —
  `project_management/flexible_time_records` and `project_management/subprojects`. It is **not** documented
  on the higher-value people / time-off / attendance streams (Airbyte's connector confirms this: it filters
  `updated_at` client-side everywhere except `shifts`).
- Per the implementing-warehouse-sources guidance, a client-side cursor that still walks every page is not
  incremental, and the two `updated_after` endpoints can't be curl-verified without a live API key. So every
  endpoint currently ships **full refresh** (`INCREMENTAL_FIELDS = {}`). Promote `flexible_time_records` /
  `subprojects` to incremental once the filter is verified against a live account with a future-date cutoff.
- For genuine change tracking, Factorial also exposes `employee_updates/*` change-feed resources and webhooks
  (`api_public/webhook_subscriptions`) — candidates for a future webhook-backed iteration.

## Synced endpoints (`settings.py`)

| Table                 | Path                                                  | Partition key |
| --------------------- | ----------------------------------------------------- | ------------- |
| employees             | `/resources/employees/employees`                      | created_at    |
| teams                 | `/resources/teams/teams`                              | —             |
| team_memberships      | `/resources/teams/memberships`                        | —             |
| locations             | `/resources/locations/locations`                      | —             |
| legal_entities        | `/resources/companies/legal_entities`                 | —             |
| contract_versions     | `/resources/contracts/contract_versions`              | created_at    |
| leaves                | `/resources/timeoff/leaves`                           | created_at    |
| leave_types           | `/resources/timeoff/leave_types`                      | —             |
| allowances            | `/resources/timeoff/allowances`                       | —             |
| attendance_shifts     | `/resources/attendance/shifts`                        | created_at    |
| expenses              | `/resources/expenses/expenses`                        | created_at    |
| payroll_supplements   | `/resources/payroll/supplements`                      | created_at    |
| flexible_time_records | `/resources/project_management/flexible_time_records` | created_at    |
| projects              | `/resources/project_management/projects`              | —             |
| candidates            | `/resources/ats/candidates`                           | created_at    |
| job_postings          | `/resources/ats/job_postings`                         | —             |
| applications          | `/resources/ats/applications`                         | created_at    |

Primary key is the integer `id` on every list resource. Partition keys are `created_at` where the field is
reliably present on every row (transactional records); lookup/config resources are left unpartitioned.

## Rate limits

- POST is documented at 200 req/min on `2025-*` endpoints. GET limits and rate-limit response headers are not
  publicly documented. The tracked session's default retry handles transient `429`/`5xx`.

## Verification status

Endpoint paths, pagination, and the `updated_after` coverage were cross-referenced against the official docs
and the Airbyte/Fivetran connector stream lists. They were **not** curl-verified against a live account (no
API key available). The connection (host, version path, `x-api-key`, 401-on-bad-key) was confirmed with an
unauthenticated curl returning `401`.
