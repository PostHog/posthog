# Calendly API inventory

Calendly REST API v2 — base URL `https://api.calendly.com`. Auth via a Personal Access Token
(`Authorization: Bearer <token>`). Docs: <https://developer.calendly.com/api-docs>.

## Conventions

- **Response shape:** list endpoints return `{"collection": [...], "pagination": {"count", "next_page", "next_page_token"}}`.
- **Pagination:** cursor-based. Follow `pagination.next_page` (a fully-formed URL carrying all query params); a `null` value ends pagination.
- **Scoping:** every list endpoint below requires an `organization` URI, resolved once per sync from `GET /users/me` → `resource.current_organization`.
- **Primary key:** every resource carries a stable `uri`.
- **Partitioning:** all endpoints expose a stable `created_at`, used for datetime partitioning.

## Endpoints synced

| Endpoint                   | Path                        | Incremental                        | Notes                      |
| -------------------------- | --------------------------- | ---------------------------------- | -------------------------- |
| `event_types`              | `/event_types`              | full refresh                       | no server-side time filter |
| `scheduled_events`         | `/scheduled_events`         | `min_start_time` (on `start_time`) | `sort=start_time:asc`      |
| `groups`                   | `/groups`                   | full refresh                       | no server-side time filter |
| `organization_memberships` | `/organization_memberships` | full refresh                       | no server-side time filter |
| `routing_forms`            | `/routing_forms`            | full refresh                       | no server-side time filter |

## Verification status & caveats

- The 401 response shape was confirmed against the live API (`{"title":"Unauthenticated", ...}`).
- Endpoint params, pagination shape, and the `min_start_time` filter are taken from the published docs and
  the Airbyte/Fivetran Calendly connectors. They were **not** curl-verified end to end here because no
  Calendly token was available in the build environment.
- `scheduled_events` incremental advances on `start_time` (the scheduled meeting time), not on
  created/updated. A late-created event whose `start_time` is below the watermark can be missed on an
  incremental run; the merge dedupes on `uri` for everything re-fetched. This mirrors the known limitation
  of the Airbyte connector. Only `scheduled_events` is marked `supports_incremental` because it is the only
  endpoint with a genuine server-side timestamp filter.

## Not yet synced

- `scheduled_events/{uuid}/invitees` — valuable (who booked) but requires per-event fan-out; deferred for the
  initial alpha.
