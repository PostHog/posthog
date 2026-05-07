# Error Tracking

## ErrorTrackingIssue (`system.error_tracking_issues`)

Error tracking issues represent grouped exceptions captured by PostHog SDKs. Each issue aggregates multiple exception events that share the same fingerprint.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key (UUID)
`team_id` | integer | NOT NULL | FK to `system.teams.id`
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`status` | varchar | NOT NULL | Issue status (see Status Values below)
`name` | text | NULL | Issue name (typically the exception type/message)
`description` | text | NULL | User-provided description

### Status Values

Status | Description
`active` | Issue is currently active and being tracked
`archived` | Issue has been archived (hidden from default views)
`resolved` | Issue has been marked as resolved
`pending_release` | Issue is pending verification in a new release
`suppressed` | Issue has been suppressed from alerts and notifications

### Key Relationships

- **Fingerprints**: Issues are linked to fingerprints (not queryable via HogQL)
- **Cohorts**: Issues can be linked to cohorts via `system.cohorts`
- **Exception Events**: Query via `events` table with `event = '$exception'` and `issue_id`

### Important Notes

- Issues group exception events by fingerprint (a hash of exception characteristics)
- The `name` field is typically auto-populated from the first exception's type/message
- Use the `events` table with `event = '$exception'` and `issue_id` to query actual exception occurrences
- Issues can be merged (combining fingerprints) or split (separating fingerprints into new issues)

---

## ErrorTrackingSymbolSet (`system.error_tracking_symbol_sets`)

Symbol sets represent uploaded source maps used to unminify JavaScript stack frames.
Rows can also track missing symbol sets so future uploads know which stack frames may need reprocessing.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key (UUID)
`team_id` | integer | NOT NULL | FK to `system.teams.id`
`ref` | text | NOT NULL | Symbol set reference matched from stack frames
`release_id` | uuid | NULL | Associated error tracking release ID
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`last_used` | timestamp with tz | NULL | Last time this symbol set was used for frame resolution
`failure_reason` | text | NULL | Reason lookup failed when the source map is missing or invalid

### Important Notes

- Internal storage pointers and content hashes are intentionally omitted from HogQL.
- Use `posthog:error-tracking-symbol-sets-list` with `status = 'valid'` or `status = 'invalid'` to check upload availability.
- Use `posthog:error-tracking-symbol-sets-list` with an exact `ref` to resolve a reference to an ID, then `posthog:error-tracking-symbol-sets-retrieve` or `posthog:error-tracking-symbol-sets-download-retrieve` by ID. Download URLs expire after one hour; use them immediately and do not echo them back unless the user explicitly asks.

---

## Common Query Patterns

**Find symbol set lookup failures:**

```sql
SELECT id, ref, failure_reason, created_at, last_used
FROM system.error_tracking_symbol_sets
WHERE failure_reason IS NOT NULL
ORDER BY created_at DESC
LIMIT 20
```

**Find symbol set metadata by reference:**

```sql
SELECT id, ref, release_id, created_at, last_used, failure_reason
FROM system.error_tracking_symbol_sets
WHERE ref = 'https://example.com/static/app.min.js'
LIMIT 1
```

**Find issues by status:**

```sql
SELECT id, name, status, created_at
FROM system.error_tracking_issues
WHERE status = 'active'
ORDER BY created_at DESC
LIMIT 20
```

**Find issues by name pattern:**

```sql
SELECT id, name, description, status
FROM system.error_tracking_issues
WHERE name ILIKE '%timeout%'
  AND status != 'archived'
```

**Count issues by status:**

```sql
SELECT status, count() AS count
FROM system.error_tracking_issues
GROUP BY status
ORDER BY count DESC
```

**Find exception events for a specific issue:**

```sql
SELECT
    timestamp,
    properties.$exception_type AS exception_type,
    properties.$exception_message AS exception_message,
    properties.$exception_source AS source,
    person.id AS user_id
FROM events
WHERE event = '$exception'
  AND issue_id = '01234567-89ab-cdef-0123-456789abcdef'
  AND timestamp >= now() - INTERVAL 7 DAY
ORDER BY timestamp DESC
LIMIT 50
```

**Aggregate exception stats by issue:**

```sql
SELECT
    issue_id,
    count() AS occurrences,
    count(DISTINCT person.id) AS affected_users,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM events
WHERE event = '$exception'
  AND isNotNull(issue_id)
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY issue_id
ORDER BY occurrences DESC
LIMIT 20
```

**Join issues with exception events:**

```sql
SELECT
    i.id,
    i.name,
    i.status
FROM system.error_tracking_issues AS i
WHERE i.status = 'active'
  AND i.id IN (
    SELECT DISTINCT issue_id
    FROM events
    WHERE event = '$exception'
      AND timestamp >= now() - INTERVAL 1 DAY
  )
ORDER BY i.created_at DESC
```
