# Customer analytics accounts

Customer analytics tracks **accounts** — the companies/organizations a team does business with — plus who owns them (relationships such as CSM or Account executive) and typed custom attributes.

**Source of truth for account ownership questions** ("who is the CSM of X?", "which accounts does Y own?"): answer them from these tables, not from warehouse CRM columns (`salesforce.*`, `hubspot.*`, ...). Warehouse copies of ownership fields can lag behind reassignments made in PostHog.

Prefer the typed `posthog:accounts-*`, `posthog:account-relationship-definitions-*`, and `posthog:custom-property-definitions-*` MCP tools for writes; use HogQL for reads and aggregations.

## Account (`system.accounts`)

One row per account.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this account belongs to
`name` | varchar | NOT NULL | Display name of the account
`external_id` | varchar | NULL | Identifier of the account in the source system
`properties` | json | NOT NULL | Account properties: role assignments `csm`, `account_executive`, `account_owner` (each `{id, email}` of a PostHog user) plus external system identifiers
`stripe_customer_id` | varchar | NULL | Extracted from `properties`
`hubspot_deal_id` | varchar | NULL | Extracted from `properties`
`billing_id` | varchar | NULL | Extracted from `properties`
`sfdc_id` | varchar | NULL | Extracted from `properties`
`zendesk_id` | varchar | NULL | Extracted from `properties`
`created_by_id` | integer | NULL | User who created the account record
`created_at` | timestamptz | NOT NULL | When the account was created
`updated_at` | timestamptz | NULL | When the account was last updated

Lazy-joined fields: `tags` (tag names), `custom_properties` (see below), `relationships` (active assignments keyed by definition id), `notebooks`.

## Account relationships (`system.account_relationship_definitions`, `system.account_relationships`)

A **relationship definition** is a team-defined relationship type between a PostHog user and an account — CSM (customer success manager), Account executive, Onboarding manager, and so on. An **account relationship** is one assignment of a user to an account for a definition, with its effective range.

### `system.account_relationship_definitions` columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this definition belongs to
`name` | varchar(400) | NOT NULL | Relationship name (e.g. `CSM`); unique within the team
`description` | text | NULL | What the relationship means
`is_single_holder` | integer | NOT NULL | `1` if only one user can hold it per account at a time
`created_by_id` | integer | NULL | User who created the definition
`created_at` | timestamptz | NOT NULL | When the definition was created
`updated_at` | timestamptz | NULL | When the definition was last updated

### `system.account_relationships` columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this assignment belongs to
`definition_id` | uuid | NOT NULL | Join to `system.account_relationship_definitions.id`
`account_id` | uuid | NOT NULL | Join to `system.accounts.id`
`user_id` | integer | NULL | Assigned PostHog user id; NULL when the user was deleted
`started_at` | timestamptz | NOT NULL | When the assignment became effective
`ended_at` | timestamptz | NULL | When the assignment ended; **NULL while active**
`created_by_id` | integer | NULL | User who made the assignment
`created_at` | timestamptz | NOT NULL | When the assignment row was created

### Important notes

- Active assignments are `ended_at IS NULL`; ended rows are kept as history.
- The role keys in `system.accounts.properties` (`csm`, `account_executive`, `account_owner`) mirror the active assignments and include the user's email; the relationships table has only `user_id`.

## Custom properties (`system.custom_property_definitions`)

Custom properties let a team attach typed attributes to accounts. A **definition** is the attribute's shape (its name and how it is typed and rendered); the per-account **values** are queried through `system.accounts` (see below). Definitions are team-scoped — one set per team, shared across all accounts.

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

### Reading per-account values (`system.accounts.custom_properties`)

There is no standalone values table. An account's current value for a definition is read through a lazy join on `system.accounts`, keyed by the definition's `id`:

```text
accounts.custom_properties.values.`<definition_id>`
```

The `<definition_id>` is a `system.custom_property_definitions.id` (backtick-quoted, since it is a UUID). Only the current value is returned — superseded (soft-deleted) values are excluded — and it is team-isolated via the accounts row.

## Common query patterns

**Who is the CSM (or any relationship holder) of an account:**

```sql
SELECT a.name, d.name AS relationship, r.user_id, r.started_at
FROM system.account_relationships r
JOIN system.account_relationship_definitions d ON d.id = r.definition_id
JOIN system.accounts a ON a.id = r.account_id
WHERE a.name ILIKE '%acme%' AND r.ended_at IS NULL
```

Shortcut when the email is enough — the role keys on `properties` mirror active assignments:

```sql
SELECT name, properties.csm.email AS csm_email
FROM system.accounts
WHERE name ILIKE '%acme%'
```

**All accounts a user holds a relationship on:**

```sql
SELECT a.name, d.name AS relationship
FROM system.account_relationships r
JOIN system.account_relationship_definitions d ON d.id = r.definition_id
JOIN system.accounts a ON a.id = r.account_id
WHERE r.user_id = 12345 AND r.ended_at IS NULL
ORDER BY a.name
```

**Assignment history of an account (including ended assignments):**

```sql
SELECT d.name AS relationship, r.user_id, r.started_at, r.ended_at
FROM system.account_relationships r
JOIN system.account_relationship_definitions d ON d.id = r.definition_id
WHERE r.account_id = '0192f000-0000-7000-8000-000000000000'
ORDER BY r.started_at DESC
```

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
