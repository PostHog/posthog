# Trello API inventory

Base URL: `https://api.trello.com/1`

Auth: API key + user token. Sent via the `Authorization` header
(`OAuth oauth_consumer_key="<key>", oauth_token="<token>"`) rather than the `?key=&token=`
query params, so the secret token never lands in request URLs (and therefore not in our
tracked-session request logs).

## Endpoints

| Schema          | Path                        | Scope  | Pagination              | Incremental     | Notes                                                 |
| --------------- | --------------------------- | ------ | ----------------------- | --------------- | ----------------------------------------------------- |
| `boards`        | `/members/me/boards`        | member | none (single request)   | full            |                                                       |
| `organizations` | `/members/me/organizations` | member | none (single request)   | full            | Trello workspaces                                     |
| `lists`         | `/boards/{id}/lists`        | board  | none (single request)   | full            | fan-out per board                                     |
| `cards`         | `/boards/{id}/cards`        | board  | none (single request)   | full            | fan-out per board; open cards only by default         |
| `checklists`    | `/boards/{id}/checklists`   | board  | none (single request)   | full            | fan-out per board                                     |
| `labels`        | `/boards/{id}/labels`       | board  | none (single request)   | full            | fan-out per board                                     |
| `members`       | `/boards/{id}/members`      | board  | none (single request)   | full            | board members; deduped across boards on `id`          |
| `actions`       | `/boards/{id}/actions`      | board  | `before`/`since` cursor | **incremental** | newest-first; `since` is a genuine server-side filter |

`boards` is fetched (id-only) before every board-scoped endpoint to drive the fan-out.

## Partitioning

Trello objects generally expose no creation timestamp, but their IDs are MongoDB ObjectIDs
whose first 8 hex chars encode the Unix creation time. We synthesise a stable `created_at`
field from the id on every row and partition on it (datetime / weekly).

## Incremental sync

Only `actions` exposes a server-side timestamp filter (`since`), so it's the only endpoint
shipped as incremental (cursor field `date`). Everything else is full refresh — matching the
Airbyte Trello connector, where only Actions supports incremental. Actions come back
descending by `date`, so the source reports `sort_mode="desc"` and pages backwards with the
`before` cursor while bounding the lower edge with `since`.

## Verification status

- `Authorization` header auth confirmed against the live API (bogus key → `401 invalid key`,
  no auth → `400 invalid token`).
- The `actions` `since` server-side filter and the exact pagination behaviour beyond 1000
  results were **not** verified against the live API (no test credentials available). The
  implementation follows the documented behaviour; if `since` turns out to be ignored on a
  given account, the sync still converges correctly because every fetched row is merged on its
  primary key. The known same-second pagination caveat (multiple objects created in the same
  second) is tolerated the same way.
