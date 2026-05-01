# LLM analytics reviews

## Trace review (`system.trace_reviews`)

Trace reviews are review records attached to LLM traces.
Each active trace can have at most one active review at a time.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Owning team
`trace_id` | varchar(255) | NOT NULL | Reviewed LLM trace ID
`created_by_id` | integer | NULL | User ID that originally created the review
`reviewed_by_id` | integer | NULL | User ID that last saved the review
`comment` | text | NULL | Optional comment attached to the review
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NULL | Last save timestamp
`deleted` | integer | NULL | Soft-delete flag (`0` = active, `1` = deleted)
`deleted_at` | timestamp with tz | NULL | When the review was soft-deleted

### Key relationships

- **Review scores**: One trace review can have many `system.trace_review_scores` rows via `review_id`
- **Pending queue items**: `trace_id` overlaps with `system.review_queue_items.trace_id`

---

## Trace review score (`system.trace_review_scores`)

Trace review scores store the saved scorer values for a review.
Each row captures one scorer definition and exactly one value type.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Owning team
`review_id` | uuid | NOT NULL | FK to `system.trace_reviews.id`
`definition_id` | uuid | NOT NULL | Stable scorer definition ID
`definition_version` | uuid | NOT NULL | Immutable scorer version ID used when saving the score
`definition_version_number` | integer | NOT NULL | Immutable scorer version number used when saving the score
`definition_config` | jsonb | NOT NULL | Snapshot of the scorer configuration used for validation
`categorical_values` | array(varchar) | NULL | Selected categorical option keys
`numeric_value` | decimal(12,6) | NULL | Saved numeric score
`boolean_value` | boolean | NULL | Saved boolean score
`created_by_id` | integer | NULL | User ID that created the score row
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NULL | Last update timestamp

### Important notes

- Exactly one of `categorical_values`, `numeric_value`, or `boolean_value` is populated per row
- Use `definition_config` when you need the historical scoring rules rather than the current scorer definition

---

## Review queue (`system.review_queues`)

Review queues are named buckets used to route traces that still need review.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Owning team
`name` | varchar(255) | NOT NULL | Display name for the queue
`created_by_id` | integer | NULL | User ID that created the queue
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NULL | Last update timestamp
`deleted` | integer | NULL | Soft-delete flag (`0` = active, `1` = deleted)
`deleted_at` | timestamp with tz | NULL | When the queue was soft-deleted

### Key relationships

- **Queue items**: One review queue can have many `system.review_queue_items` rows via `queue_id`

---

## Review queue item (`system.review_queue_items`)

Review queue items are pending trace assignments inside review queues.
An active trace can only be pending in one queue at a time.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Owning team
`queue_id` | uuid | NOT NULL | FK to `system.review_queues.id`
`trace_id` | varchar(255) | NOT NULL | Pending LLM trace ID
`created_by_id` | integer | NULL | User ID that queued the trace
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NULL | Last update timestamp
`deleted` | integer | NULL | Soft-delete flag (`0` = active, `1` = deleted)
`deleted_at` | timestamp with tz | NULL | When the queue item was soft-deleted

### Important notes

- Queue items represent pending work, not completed reviews
- Saving a matching trace review may soft-delete the pending queue item

---

## Common query patterns

**List active trace reviews with their saved score counts:**

```sql
SELECT
    r.id,
    r.trace_id,
    r.reviewed_by_id,
    r.updated_at,
    count(s.id) AS score_count
FROM system.trace_reviews AS r
LEFT JOIN system.trace_review_scores AS s ON s.review_id = r.id
WHERE r.deleted = 0
GROUP BY r.id, r.trace_id, r.reviewed_by_id, r.updated_at
ORDER BY r.updated_at DESC
LIMIT 20
```

**List active review queues with pending item counts:**

```sql
SELECT
    q.id,
    q.name,
    count(i.id) AS pending_item_count
FROM system.review_queues AS q
LEFT JOIN system.review_queue_items AS i
    ON i.queue_id = q.id
   AND i.deleted = 0
WHERE q.deleted = 0
GROUP BY q.id, q.name
ORDER BY q.name ASC
```

**Find pending traces in a specific review queue:**

```sql
SELECT
    i.trace_id,
    i.created_at,
    i.created_by_id
FROM system.review_queue_items AS i
WHERE i.queue_id = '01234567-89ab-cdef-0123-456789abcdef'
  AND i.deleted = 0
ORDER BY i.created_at ASC
LIMIT 100
```

**List review scores for recently updated reviews:**

```sql
SELECT
    r.trace_id,
    s.definition_id,
    s.definition_version_number,
    s.categorical_values,
    s.numeric_value,
    s.boolean_value
FROM system.trace_review_scores AS s
INNER JOIN system.trace_reviews AS r ON r.id = s.review_id
WHERE r.deleted = 0
ORDER BY r.updated_at DESC, s.created_at ASC
LIMIT 100
```
