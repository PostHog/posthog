---
name: fixing-group-key-too-long
description: >
  Diagnoses and fixes the `group_key_too_long` ingestion warning — a `$groupidentify` event was dropped because its group key exceeded 400 characters.
  Use when a user asks why a group isn't appearing or updating, why group analytics are missing an organization, or when `ingestion-warnings-list` shows `group_key_too_long`.
---

# Fixing `group_key_too_long`

A `$groupidentify` event was **dropped** because its `$group_key` was longer than 400 characters.
Category `size`, severity `error`: the group was not created or updated.

## What it means in your code

A group key should be a short, stable identifier — `org_1042`, a UUID, a domain. A key over 400 characters almost always means the wrong value was passed:

- a serialized object or JSON blob where the ID should be,
- a JWT/session token,
- a URL with query parameters,
- a concatenation bug (`${orgName}${orgDescription}` instead of `${orgId}`).

## Diagnose

1. `ingestion-warnings-list` with `type: group_key_too_long`. The sample details include the (truncated) `groupKey`, its length, and the 400 limit — the value itself usually reveals what got passed.
2. Grep the app for `groupIdentify` / `group(` callsites and check what feeds the key argument.

## Fix

Pass a short, stable ID as the key, and keep everything descriptive in the properties:

```js
posthog.group('organization', org.id, {
  name: org.name,
  plan: org.plan,
})
```

The key is the group's permanent identity — changing it later creates a **new** group, so pick the stable database ID, not a name or email that can change.

## Verify

Re-run the flow, then re-query `ingestion-warnings-list` with a post-fix `since` — no new occurrences — and confirm the group appears with its properties.

## Related

- `resolving-ingestion-warnings` — the triage entry point.
- `fixing-message-size-too-large` — if group _properties_ (not the key) are oversized, they inflate every event tagged with the group.
