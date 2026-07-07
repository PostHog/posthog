# Customer analytics custom properties

Custom properties let a team attach typed attributes to customer analytics accounts. A **definition** is the attribute's shape (its name and how it is typed and rendered); the per-account **values** are queried through `system.accounts` (see below). Definitions are team-scoped — one set per team, shared across all accounts.

Prefer the typed `posthog:custom-property-definitions-*` MCP tools for writes; use HogQL for reads and aggregations.

## CustomPropertyDefinition (`system.custom_property_definitions`)

Team-scoped definitions of custom account properties — the attribute side of the model. One row per property.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key. Use this to read an account's value (see below)
`team_id` | integer | NOT NULL | Team this definition belongs to
`name` | varchar(400) | NOT NULL | Human-readable property name; unique within the team
`description` | text | NULL | Optional description of what the property represents
`display_type` | varchar(20) | NOT NULL | How the value is typed and rendered: `text`, `number`, `currency`, `percent`, `date`, `datetime`, or `boolean`
`is_big_number` | integer | NOT NULL | `1` if large numeric values are abbreviated (e.g. 10,000 -> 10K), `0` otherwise. Only meaningful for numeric display types
`created_by_id` | integer | NULL | User who created the definition
`created_at` | timestamptz | NOT NULL | When the definition was created
`updated_at` | timestamptz | NULL | When the definition was last updated

### Important notes

- `is_big_number` surfaces as an integer (`0`/`1`), not a boolean.
- `display_type` is the rendering hint; effective data type is string for `text`, numeric for `number`/`currency`/`percent`, datetime for `date`/`datetime`, and boolean for `boolean`.

## Reading per-account values (`system.accounts.custom_properties`)

There is no standalone values table. An account's current value for a definition is read through a lazy join on `system.accounts`, keyed by the definition's `id`:

```text
accounts.custom_properties.values.`<definition_id>`
```

The `<definition_id>` is a `system.custom_property_definitions.id` (backtick-quoted, since it is a UUID). Only the current value is returned — superseded (soft-deleted) values are excluded — and it is team-isolated via the accounts row.

## Common query patterns

**List all custom property definitions for a team:**

```sql
SELECT id, name, display_type, is_big_number
FROM system.custom_property_definitions
ORDER BY name
```

**Find numeric definitions:**

```sql
SELECT id, name, display_type
FROM system.custom_property_definitions
WHERE display_type IN ('number', 'currency', 'percent')
ORDER BY name
```

**Read a specific custom property value across accounts** (substitute a real definition id from the query above):

```sql
SELECT id, name, custom_properties.values.`0192f000-0000-7000-8000-000000000000` AS plan_tier
FROM system.accounts
ORDER BY name
```
