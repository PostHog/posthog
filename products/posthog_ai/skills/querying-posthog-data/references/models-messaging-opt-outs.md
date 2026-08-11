# Messaging opt-outs

## Message recipient preferences (`system.message_recipient_preferences`)

Messaging preferences per recipient, one row per recipient. The `preferences` map records opt-outs and opt-ins per message category.

### Columns

Column | Type | Nullable | Description
`id` | string (UUID) | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Owning team
`identifier` | varchar(512) | NOT NULL | Recipient identifier, usually an email address
`preferences` | jsonb | NOT NULL | Map of message category ID to `OPTED_OUT` or `OPTED_IN`. The key `$all` covers all marketing messages; other keys are `message_categories` ids
`deleted` | integer (0/1) | NOT NULL | 1 if soft-deleted; filter with `deleted = 0`
`created_at` | timestamp with tz | NOT NULL | When the recipient was first recorded
`updated_at` | timestamp with tz | NOT NULL | When preferences last changed

## Message categories (`system.message_categories`)

Message categories recipients can opt out of, one row per category. Category IDs are the keys in `message_recipient_preferences.preferences`.

### Columns

Column | Type | Nullable | Description
`id` | string (UUID) | NOT NULL | Primary key, used as the key in recipient preferences
`team_id` | integer | NOT NULL | Owning team
`key` | varchar(64) | NOT NULL | Stable category key used in the API, e.g. `newsletter`
`name` | varchar(128) | NOT NULL | Display name
`description` | text | NOT NULL | Internal description
`public_description` | text | NOT NULL | Description shown to recipients on the preferences page
`category_type` | varchar | NOT NULL | `marketing` (opt-out applies) or `transactional`
`deleted` | integer (0/1) | NOT NULL | 1 if soft-deleted; filter with `deleted = 0`
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp

### Query Examples

```sql
-- Recipients opted out of all marketing messages
SELECT identifier, updated_at
FROM system.message_recipient_preferences
WHERE deleted = 0 AND JSONExtractString(preferences, '$all') = 'OPTED_OUT'
ORDER BY updated_at DESC

-- Opt-out counts per category
SELECT c.key, c.name, count() AS opted_out
FROM system.message_recipient_preferences AS p
JOIN system.message_categories AS c ON JSONExtractString(p.preferences, toString(c.id)) = 'OPTED_OUT'
WHERE p.deleted = 0 AND c.deleted = 0
GROUP BY c.key, c.name
ORDER BY opted_out DESC

-- Is a specific recipient opted out of a category (falling back to the all-marketing flag)?
SELECT identifier,
       JSONExtractString(preferences, (SELECT toString(id) FROM system.message_categories WHERE key = 'newsletter')) AS category_status,
       JSONExtractString(preferences, '$all') AS all_marketing_status
FROM system.message_recipient_preferences
WHERE deleted = 0 AND identifier = 'ally@example.com'
```
