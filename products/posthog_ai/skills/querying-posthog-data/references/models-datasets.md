# AI observability datasets

Datasets hold curated inputs, expected outputs, and optional trace provenance for offline evaluation.
Dataset items have stable IDs and immutable content versions.
Every item mutation creates a dataset revision, which makes prior dataset contents queryable as exact snapshots.

## Dataset (`system.datasets`)

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Stable dataset ID
`team_id` | integer | NOT NULL | Owning project
`name` | text | NOT NULL | Dataset name, unique within the project
`description` | text | NOT NULL | Description of what the dataset contains
`metadata` | jsonb | NOT NULL | Dataset-level metadata object
`archived` | boolean | NOT NULL | Whether the dataset is archived
`current_revision_id` | uuid | NULL | Latest committed revision, or NULL before the first item mutation
`created_by_id` | integer | NULL | User who created the dataset
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NULL | Last change to dataset fields or item contents

## Dataset revision (`system.dataset_revisions`)

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Dataset revision ID
`team_id` | integer | NOT NULL | Owning project
`dataset_id` | uuid | NOT NULL | Parent dataset ID
`revision` | integer | NOT NULL | Monotonic revision number within the dataset
`created_by_id` | integer | NULL | User who committed the revision
`created_at` | timestamp with tz | NOT NULL | Commit timestamp

Dataset revisions describe item-content snapshots.
Editing dataset name, description, or metadata does not create a revision.

## Dataset item (`system.dataset_items`)

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Stable item ID shared by every version
`team_id` | integer | NOT NULL | Owning project
`dataset_id` | uuid | NOT NULL | Parent dataset ID
`client_item_id` | varchar(255) | NULL | Optional caller-owned stable key, unique within the dataset
`current_version_id` | uuid | NULL | Latest immutable version ID
`created_by_id` | integer | NULL | User who created the stable item
`created_at` | timestamp with tz | NOT NULL | Item creation timestamp
`updated_at` | timestamp with tz | NULL | Timestamp of the latest item version

The stable item row does not carry content or archive state.
Join `current_version_id` to `system.dataset_item_versions.id` for the current values.

## Dataset item version (`system.dataset_item_versions`)

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Immutable item version ID
`team_id` | integer | NOT NULL | Owning project
`dataset_id` | uuid | NOT NULL | Parent dataset ID
`dataset_item_id` | uuid | NOT NULL | Stable item ID
`dataset_revision_id` | uuid | NOT NULL | Revision that introduced this version
`version` | integer | NOT NULL | Monotonic version number within the item
`archived` | boolean | NOT NULL | Whether this version archives the item
`input` | jsonb | NOT NULL | Input supplied to the system under test
`expected_output` | jsonb | NULL | User-authored target output
`source_output` | jsonb | NULL | Actual output copied from a source trace
`metadata` | jsonb | NOT NULL | Item metadata object
`source_trace_id` | varchar(255) | NULL | Source AI trace ID
`source_event_id` | varchar(255) | NULL | Source event ID within the trace
`source_timestamp` | timestamp with tz | NULL | Timestamp used to retrieve the source trace event
`created_by_id` | integer | NULL | User who created this version
`created_at` | timestamp with tz | NOT NULL | Version creation timestamp

Source output and trace provenance are immutable after item creation.
User edits create another version and may change only input, expected output, metadata, and archive state.

## Relationships

- `system.dataset_revisions.dataset_id` references `system.datasets.id`.
- `system.dataset_items.dataset_id` references `system.datasets.id`.
- `system.dataset_items.current_version_id` references `system.dataset_item_versions.id`.
- `system.dataset_item_versions.dataset_item_id` references `system.dataset_items.id`.
- `system.dataset_item_versions.dataset_revision_id` references `system.dataset_revisions.id`.
- `system.dataset_item_versions.dataset_id` is the direct parent dataset used for access control.

## Query patterns

List current active items in a dataset:

```sql
SELECT
    i.id,
    i.client_item_id,
    v.version,
    v.input,
    v.expected_output,
    v.source_output,
    v.metadata
FROM system.dataset_items AS i
INNER JOIN system.dataset_item_versions AS v ON v.id = i.current_version_id
WHERE i.dataset_id = '01234567-89ab-cdef-0123-456789abcdef'
  AND v.archived = false
ORDER BY i.created_at DESC
LIMIT 100
```

Reconstruct active items at dataset revision 7:

```sql
SELECT
    i.id,
    i.client_item_id,
    argMax(v.version, r.revision) AS version,
    argMax(v.input, r.revision) AS input,
    tupleElement(argMax(tuple(v.expected_output), r.revision), 1) AS expected_output,
    tupleElement(argMax(tuple(v.source_output), r.revision), 1) AS source_output,
    argMax(v.metadata, r.revision) AS metadata
FROM system.dataset_items AS i
INNER JOIN system.dataset_item_versions AS v ON v.dataset_item_id = i.id
INNER JOIN system.dataset_revisions AS r ON r.id = v.dataset_revision_id
WHERE i.dataset_id = '01234567-89ab-cdef-0123-456789abcdef'
  AND r.revision <= 7
GROUP BY i.id, i.client_item_id
HAVING argMax(v.archived, r.revision) = false
ORDER BY i.id
```

List the immutable history of one item:

```sql
SELECT
    version,
    archived,
    input,
    expected_output,
    metadata,
    dataset_revision_id,
    created_by_id,
    created_at
FROM system.dataset_item_versions
WHERE dataset_item_id = '01234567-89ab-cdef-0123-456789abcdef'
ORDER BY version DESC
```
