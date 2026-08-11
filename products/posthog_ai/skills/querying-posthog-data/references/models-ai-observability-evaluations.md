# AI observability evaluations

## Evaluation directory (`system.evaluation_directories`)

Evaluation directories organize online evaluations. Directories are flat. An evaluation with no directory is at the top level.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Directory UUID
`team_id` | integer | NOT NULL | Owning team
`name` | varchar(400) | NOT NULL | Directory name
`created_by_id` | integer | NULL | User who created the directory
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NULL | Last update timestamp

## Evaluation (`system.evaluations`)

Online evaluations score AI generations or traces. Evaluation results are stored as `$ai_evaluation` events, not on this configuration table.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Evaluation UUID
`team_id` | integer | NOT NULL | Owning team
`directory_id` | uuid | NULL | FK to `system.evaluation_directories.id`; NULL means the top level
`name` | varchar(400) | NOT NULL | Evaluation name
`description` | text | NOT NULL | Evaluation description
`enabled` | boolean | NOT NULL | Whether the evaluation is active
`status` | varchar(20) | NOT NULL | Current evaluation status
`status_reason` | varchar(50) | NULL | Reason for the current status, when available
`evaluation_type` | varchar(50) | NOT NULL | Evaluation implementation type
`evaluation_config` | jsonb | NOT NULL | Evaluation-specific configuration
`output_type` | varchar(50) | NOT NULL | Evaluation result type
`output_config` | jsonb | NOT NULL | Evaluation output configuration
`conditions` | jsonb | NOT NULL | Conditions that select matching input
`target` | varchar(20) | NOT NULL | Unit evaluated, such as a generation or trace
`target_config` | jsonb | NOT NULL | Target-specific configuration
`model_configuration_id` | uuid | NULL | Model configuration used by an LLM judge evaluation
`created_by_id` | integer | NULL | User who created the evaluation
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp
`deleted` | boolean | NOT NULL | Whether the evaluation has been deleted

### Important notes

- Filter on `deleted = false` to match the default online evals list.
- Use `directory_id IS NULL` for evaluations at the top level.
- Deleting a directory preserves its evaluations and sets their `directory_id` to NULL.

## Common query patterns

**List directories with active evaluation counts:**

```sql
SELECT
    d.id,
    d.name,
    count(e.id) AS evaluation_count
FROM system.evaluation_directories AS d
LEFT JOIN system.evaluations AS e
    ON e.directory_id = d.id
   AND e.deleted = false
GROUP BY d.id, d.name
ORDER BY d.name ASC
```

**List active evaluations at the top level:**

```sql
SELECT id, name, evaluation_type, status, updated_at
FROM system.evaluations
WHERE deleted = false
  AND directory_id IS NULL
ORDER BY updated_at DESC
LIMIT 100
```
