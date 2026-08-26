# Customer analytics accounts and feature requests

Customer analytics tracks **accounts**, their owners and custom properties, and the feature requests linked to those accounts.

**Source of truth for account ownership questions** ("who is the CSM of X?", "which accounts does Y own?"): answer them from these tables, not from warehouse CRM columns (`salesforce.*`, `hubspot.*`, ...). Warehouse copies of ownership fields can lag behind reassignments made in PostHog.

Prefer the typed `posthog:accounts-*`, `posthog:account-relationship-definitions-*`, `posthog:custom-property-definitions-*`, and `posthog:feature-request*` MCP tools for writes. Use HogQL for reads and aggregations.

## Account (`system.accounts`)

One row per account.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this account belongs to
`name` | varchar | NOT NULL | Display name of the account
`external_id` | varchar | NULL | Identifier of the account in the source system
`properties` | json | NOT NULL | Account properties for email matching (`email_domains`, `known_emails`) and external system identifiers. Legacy role keys may remain only until backfill and are not authoritative
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
- Do not read `csm`, `account_executive`, or `account_owner` from `system.accounts.properties`. These keys are retired, and the relationship backfill removes them. Use `system.account_relationships` for ownership.
- `system.account_relationships` exposes `user_id`, but the customer analytics HogQL system tables do not expose a current user email field. Use an account API when current organization member details are required.

## Feature requests

A feature request records a customer need across one or more accounts. Evidence belongs to a specific request and account pair. Product areas categorize requests, and history records each successful save.

The tables apply account access rules. `system.feature_requests` includes a request when the caller can access at least one active linked account. The account links and evidence tables exclude inaccessible and unlinked accounts.

### `system.feature_requests` columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this request belongs to
`title` | varchar(400) | NOT NULL | Customer-facing request title
`description` | text | NOT NULL | Customer-facing description in Markdown
`status` | varchar(32) | NOT NULL | `requested`, `planned`, `completed`, `wont_fix`, or `duplicate`
`priority` | varchar(16) | NULL | `high`, `medium`, `low`, or NULL
`archived_at` | timestamptz | NULL | When the request was archived. NULL means active
`archived_by_id` | integer | NULL | User who archived the request
`version` | integer | NOT NULL | Version used for optimistic concurrency
`created_by_id` | integer | NULL | User who created the request
`updated_by_id` | integer | NULL | User who last updated the request
`created_at` | timestamptz | NOT NULL | When the request was created
`updated_at` | timestamptz | NOT NULL | When the request was last updated

### `system.feature_request_account_links` columns

One row per active request and account pair visible to the caller.

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key and parent key for evidence
`team_id` | integer | NOT NULL | Team this link belongs to
`feature_request_id` | uuid | NOT NULL | Join to `system.feature_requests.id`
`account_id` | uuid | NOT NULL | Join to `system.accounts.id`
`created_at` | timestamptz | NOT NULL | When the account was first linked
`updated_at` | timestamptz | NULL | When the link last changed

### `system.feature_request_evidence` columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this evidence belongs to
`account_link_id` | uuid | NOT NULL | Join to `system.feature_request_account_links.id`
`summary` | text | NOT NULL | Internal evidence summary
`customer_quote` | text | NOT NULL | Customer quote
`source` | varchar(200) | NOT NULL | Free-form source name
`source_url` | varchar(2000) | NOT NULL | Source URL or an empty string
`requested_on` | date | NULL | Date the account made the request
`image_ids` | array(text) | NOT NULL | Uploaded image UUIDs attached to the evidence, in display order
`created_by_id` | integer | NULL | User who added the evidence
`updated_by_id` | integer | NULL | User who last updated the evidence
`created_at` | timestamptz | NOT NULL | When the evidence was added
`updated_at` | timestamptz | NOT NULL | When the evidence was last updated

### Product area tables

`system.feature_request_product_areas` defines the available areas. `system.feature_request_product_area_links` joins visible requests to those areas.

`system.feature_request_product_areas` column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this area belongs to
`name` | varchar(200) | NOT NULL | Product area name
`display_order` | integer | NOT NULL | Selector position. Lower values appear first
`is_active` | integer | NOT NULL | `1` if editors can select the area, `0` otherwise
`created_by_id` | integer | NULL | User who created the area
`updated_by_id` | integer | NULL | User who last updated the area
`created_at` | timestamptz | NOT NULL | When the area was created
`updated_at` | timestamptz | NOT NULL | When the area was last updated

`system.feature_request_product_area_links` column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this link belongs to
`feature_request_id` | uuid | NOT NULL | Join to `system.feature_requests.id`
`product_area_id` | uuid | NOT NULL | Join to `system.feature_request_product_areas.id`
`created_at` | timestamptz | NOT NULL | When the area was linked

### `system.feature_request_history` columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this history entry belongs to
`feature_request_id` | uuid | NOT NULL | Join to `system.feature_requests.id`
`changed_fields` | array(varchar) | NOT NULL | Names of the fields changed in this save. Before and after values are not exposed
`is_initial` | integer | NOT NULL | `1` for the initial snapshot, `0` otherwise
`source` | varchar(32) | NOT NULL | System that recorded the change
`actor_id` | integer | NULL | User who changed the request
`changed_at` | timestamptz | NOT NULL | When the request changed

### Feature request query patterns

**List active requests and their affected accounts:**

```sql
SELECT r.id, r.title, r.status, r.priority, a.id AS account_id, a.name AS account_name
FROM system.feature_requests r
JOIN system.feature_request_account_links l ON l.feature_request_id = r.id
JOIN system.accounts a ON a.id = l.account_id
WHERE r.archived_at IS NULL
ORDER BY r.updated_at DESC
```

**Count evidence items by request and account:**

```sql
SELECT r.title, a.name AS account_name, count(e.id) AS evidence_count
FROM system.feature_requests r
JOIN system.feature_request_account_links l ON l.feature_request_id = r.id
JOIN system.accounts a ON a.id = l.account_id
LEFT JOIN system.feature_request_evidence e ON e.account_link_id = l.id
GROUP BY r.id, r.title, a.id, a.name
ORDER BY evidence_count DESC
```

**List requests for one product area:**

```sql
SELECT r.id, r.title, r.status, p.name AS product_area
FROM system.feature_requests r
JOIN system.feature_request_product_area_links l ON l.feature_request_id = r.id
JOIN system.feature_request_product_areas p ON p.id = l.product_area_id
WHERE p.name ILIKE '%analytics%'
ORDER BY r.updated_at DESC
```

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
WHERE a.name ILIKE '%acme%'
  AND d.name = 'CSM'
  AND r.ended_at IS NULL
```

Do not use `properties.csm.email` as an email shortcut. The role keys in account properties are retired and are stripped by `backfill_account_relationships`. HogQL relationship tables return `user_id`; use an account API when current organization member details are required.

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
