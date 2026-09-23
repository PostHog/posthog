# Calendly API inventory

Calendly REST API v2 — base URL `https://api.calendly.com`. Auth via a Personal Access Token
(`Authorization: Bearer <token>`). Docs: <https://developer.calendly.com/api-docs>.

## Conventions

- **Response shape:** list endpoints return `{"collection": [...], "pagination": {"count", "next_page", "next_page_token"}}`.
- **Pagination:** cursor-based. Follow `pagination.next_page` (a fully-formed URL carrying all query params); a `null` value ends pagination.
- **Scoping:** the top-level list endpoints require an `organization` URI, resolved once per sync from `GET /users/me` → `resource.current_organization`. `/contacts` is account-scoped and takes no such param; the fan-out children are scoped by their parent instead.
- **Primary key:** every resource carries a stable `uri`.
- **Partitioning:** all endpoints expose a stable `created_at`, used for datetime partitioning.

## Endpoints synced

| Endpoint                   | Path                        | Incremental                        | Notes                                 |
| -------------------------- | --------------------------- | ---------------------------------- | ------------------------------------- |
| `event_types`              | `/event_types`              | full refresh                       | no server-side time filter            |
| `scheduled_events`         | `/scheduled_events`         | `min_start_time` (on `start_time`) | `sort=start_time:asc`                 |
| `groups`                   | `/groups`                   | full refresh                       | no server-side time filter            |
| `organization_memberships` | `/organization_memberships` | full refresh                       | no server-side time filter            |
| `routing_forms`            | `/routing_forms`            | full refresh                       | no server-side time filter            |
| `contacts`                 | `/contacts`                 | full refresh                       | account-scoped, `sort=created_at:asc` |

### Fanned out over a parent

| Endpoint                   | Path                                  | Parent             | Notes                                                  |
| -------------------------- | ------------------------------------- | ------------------ | ------------------------------------------------------ |
| `invitees`                 | `/scheduled_events/{uuid}/invitees`   | `scheduled_events` | parent UUID in the path, `sort=created_at:asc`         |
| `routing_form_submissions` | `/routing_form_submissions?form=`     | `routing_forms`    | parent URI as a query param, `sort=created_at:asc`     |
| `event_type_memberships`   | `/event_type_memberships?event_type=` | `event_types`      | Calendly calls these event type hosts; takes no `sort` |

None of the four accepts a server-side timestamp filter, so all are full refresh and merge on `uri`.
Each object's `uri` is globally unique — an invitee URI embeds its event's UUID — so no fan-out child
needs its parent id in the primary key.

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
- The fanned-out endpoints and `/contacts` were taken from the Stoplight project behind
  developer.calendly.com (project `cHJqOjY4NTM`): paths, query params, required scopes and response shapes
  come from its operation definitions. `event_type_memberships` documents `created_at` but does not mark it
  required, so a row without it lands in the unknown-date partition rather than failing the sync.
- `/contacts` needs the `contacts:read` scope. A token without it gets a 403, which
  `get_non_retryable_errors` already turns into a permanent failure with a message, and only that table
  fails.

## Not yet synced

- `/group_relationships`, `/activity_log_entries`, `/outgoing_communications`,
  `/user_availability_schedules`, the Notetaker recaps and transcripts, and
  `/organizations/{uuid}/invitations`.
