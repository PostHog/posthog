---
name: managing-path-cleaning-rules
description: 'Inspects URL paths and proposes, tests, orders, and applies project-level path cleaning rules so dynamic segments (numeric IDs, UUIDs, slugs, dates) collapse into readable aliases. Use when the user says "clean the paths", "normalize URLs", "group similar pages", "too many distinct paths", "/users/123 and /users/456 are the same page", "set up path cleaning", or asks why a Web analytics or Paths breakdown is fragmented across thousands of nearly-identical URLs. Covers regex syntax (re2), alias placeholder convention, rule ordering, the test workflow, and applying rules via the path-cleaning-rules-update MCP tool.'
---

# Managing path cleaning rules

Path cleaning rules normalize `$pathname` and `$entry_pathname` so that pages
sharing the same template (`/users/123/profile`, `/users/456/profile`, …) collapse
into one row (`/users/<id>/profile`) in Web analytics tiles, Paths insights, and
any HogQL query that calls `apply_path_cleaning`. They are the right answer when
a breakdown is fragmented across thousands of near-identical URLs.

This skill teaches you how to:

- recognize when path cleaning is the right tool
- inspect real paths to find what needs cleaning
- write `regex` + `alias` rules in re2 syntax with the project's placeholder
  convention
- test rules before saving them
- order rules so specific patterns aren't swallowed by generic ones
- apply the rules via MCP

## Data model

`Team.path_cleaning_filters` is a JSON list of `PathCleaningFilter` objects:

```json
{
  "regex": "/users/\\d+/profile",
  "alias": "/users/<id>/profile",
  "order": 0
}
```

- **`regex`** — a [re2](https://github.com/google/re2/wiki/Syntax) pattern. No
  need to escape `/`. Anchor with `^` / `$` when you mean it.
- **`alias`** — the literal replacement. Use angle-bracket placeholders
  (`<id>`, `<slug>`, `<uuid>`, `<date>`) by convention so the cleaned path stays
  human-readable. The alias is _not_ a regex template — backreferences are not
  supported.
- **`order`** — integer. Rules apply **sequentially** in `order` ascending,
  each rule's output feeds the next.

Application is `replaceRegexpAll(pathname, regex, alias)` per rule, chained.
Source: `posthog/hogql/property.py:613`.

## Workflow

### 1. Confirm path cleaning is the right move

Ask yourself: is the user complaining about cardinality (too many distinct paths
in a chart), or do they want a per-URL drill-down? Path cleaning is for the
former. If they want per-URL data, suggest a property filter on `$pathname`
instead.

### 2. Inspect the real paths

Don't guess at patterns — query them. With the `execute-sql` MCP tool:

```sql
SELECT properties.$pathname AS path, count() AS views
FROM events
WHERE event = '$pageview'
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY path
ORDER BY views DESC
LIMIT 200
```

Scan the result for:

- numeric IDs: `/users/123`, `/orders/4242`
- UUIDs: `/sessions/8f3c1a3b-…`
- slugs: `/posts/why-i-love-posthog`
- dates: `/archive/2024-09-12`
- locales: `/en-US/`, `/fr-FR/`
- pagination: `?page=3`, `/page/3/`

### 3. Draft regex + alias

| Pattern             | Example match          | `regex`                      | `alias`                |
| ------------------- | ---------------------- | ---------------------------- | ---------------------- |
| Numeric segment     | `/users/123/profile`   | `/users/\d+/profile`         | `/users/<id>/profile`  |
| UUID v4             | `/sessions/8f3c1a3b-…` | `/sessions/[0-9a-f-]{36}`    | `/sessions/<uuid>`     |
| Slug                | `/posts/why-posthog`   | `/posts/[a-z0-9-]+$`         | `/posts/<slug>`        |
| ISO date            | `/archive/2024-09-12`  | `/archive/\d{4}-\d{2}-\d{2}` | `/archive/<date>`      |
| Locale prefix       | `/en-US/about`         | `^/[a-z]{2}-[A-Z]{2}/`       | `/<locale>/`           |
| Trailing query/page | `/blog?page=3`         | `\?page=\d+$`                | (empty alias drops it) |

Anchoring rules of thumb:

- start the regex with `^` only when the segment must be at the beginning of
  the path
- end with `$` to keep a generic rule (e.g. `\d+$`) from matching mid-path
  segments

### 4. Test before saving

Three options, pick one:

- **Settings page tester**: `/settings/project#path_cleaning` has a built-in
  "test path" input that replays the full ordered chain.
- **Project HogQL** (via `execute-sql`):

  ```sql
  SELECT replaceRegexpAll('/users/42/profile', '/users/\d+/profile', '/users/<id>/profile')
  ```

  Chain `replaceRegexpAll` calls in the same order the rules will run if you
  want to verify multi-rule interaction.

- **Built-in AI helper**: there is already an `AiRegexHelper` modal accessible
  from the rule editor (`Help me with Regex` button) that turns natural
  language into a regex. Suggest it to the user when they say "I don't know
  regex" — but always validate the output against real paths via the tester.

### 5. Order rules from most-specific to most-general

Sequential application means a generic rule placed first will swallow
everything that should have hit a specific rule.

```text
order=0  /users/me/profile        →  /users/me/profile     (specific, runs first)
order=1  /users/\d+/profile       →  /users/<id>/profile
order=2  /users/[a-z0-9-]+        →  /users/<slug>          (catch-all, runs last)
```

If `/users/[a-z0-9-]+` ran first it would also match `/users/me/profile` and
make the more specific rule unreachable.

### 6. Apply via MCP

Prefer the `path-cleaning-rules-update` tool. It reads the current rules,
applies granular operations (`append`, `insert`, `replace`, `remove`,
`reorder`), auto-numbers `order`, and — unless you pass `confirm: true` —
returns a **preview** of the resulting rules without saving. Pass
`sample_paths` to see how the resulting set rewrites real paths.

Preview first (no `confirm`), surface it to the user, then apply:

```json
{
  "operations": [
    { "action": "append", "alias": "/users/<id>/profile", "regex": "/users/\\d+/profile" }
  ],
  "sample_paths": ["/users/123/profile", "/users/me/profile"],
  "confirm": true
}
```

Because the tool does the read-modify-write for you, you don't have to fetch
the full list, renumber `order`, or risk clobbering existing rules — the common
failure mode when editing `path_cleaning_filters` directly.

If you must fall back to `project-settings-update` (whole-list overwrite),
always **read the existing rules first** and merge — overwriting silently
destroys whatever the team has already configured.

## Where the rules apply

When the user (or a HogQL query) opts in:

- Web analytics: the **Path cleaning** toggle in the page header
  (`PathCleaningToggle.tsx`)
- Paths insights: the path cleaning toggle in the insight filters
- HogQL: any query that calls `apply_path_cleaning(path_expr, team)`

The rules are stored once per project — they are not insight-scoped.

## Common pitfalls

- **Backreferences in `alias` need double-escaping** — ClickHouse's
  `replaceRegexpAll` supports `\0` (whole match) and `\1`–`\9` (capture
  groups). In a JSON field or SQL string literal the backslash must be
  doubled, so use `\\1` in `path_cleaning_filters` / HogQL to get the `\1`
  backreference at the ClickHouse layer.
- **Forgetting `$`** — `\d+` without an end anchor matches every numeric run
  in any path, so `/blog/2024-09-12/post` becomes
  `/blog/<num>-<num>-<num>/post` when you only meant to match the year
  segment. Use `\d+$` or `\d+(/|$)` depending on intent.
- **Escaping `/`** — re2 does not require it. `\/` works but adds noise.
- **Case sensitivity** — re2 is case-sensitive by default. Use `(?i)` at the
  start of the pattern for case-insensitive matching, e.g. `(?i)/users/\d+`.
- **Replacing the whole list** — the raw `path_cleaning_filters` field is
  overwrite, not append. Use `path-cleaning-rules-update` (which does the
  read-modify-write for you) instead of hand-editing the field; if you must
  edit it directly, always start from the current list.
- **Rules apply globally** — adding a rule can change historical numbers in
  every Web analytics / Paths chart that has cleaning enabled. Warn the user
  before applying anything destructive.
