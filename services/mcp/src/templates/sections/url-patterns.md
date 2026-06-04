### URL patterns

PostHog app links must be full URLs (origin + path) — bare paths aren't clickable in MCP clients like Cursor or Claude Desktop. Use Markdown with descriptive anchor text, e.g. `[Cohorts](https://us.posthog.com/project/1/cohorts)`. Never include `/-/`.

- If a tool result has a `*url` field (e.g. `_posthogUrl`), surface it verbatim — never rewrite or strip it.
- Otherwise build the link from the Base URL in the active-environment block (don't double-prefix):
  - Project-scoped paths → Base URL + `/project/:id`: `/settings/<section-id>` (hyphenated, e.g. `/settings/environment-replay`, `/settings/user-api-keys`), `/data-management/events`, `/data-management/properties`, and most pages.
  - Org-/account-level paths → Base URL only (no `/project/:id`): first segment `organization`, `me`, `account`, or `instance` — e.g. billing is `/organization/billing`.
- When you only have an entity id (e.g. from an `execute-sql` or query result that carries no `*url` field), use the exact project-scoped slug below. These are the canonical paths — do not guess, abbreviate, or singularize them:
  - Person → `/persons/:distinct_id` (plural — `/person/:id` is wrong and 404s)
  - Insight → `/insights/:short_id`
  - Dashboard → `/dashboard/:id` (singular)
  - Feature flag → `/feature_flags/:id`
  - Experiment → `/experiments/:id`
  - Survey → `/surveys/:id`
  - Cohort → `/cohorts/:id`
  - Action → `/data-management/actions/:id`
  - Annotation → `/data-management/annotations/:id`
  - Error tracking issue → `/error_tracking/:issue_id`
  - Session replay → `/replay/:session_id`
- If you are unsure of the correct slug, link to the list page (e.g. `/persons`) or omit the link rather than guess a path that may 404.
