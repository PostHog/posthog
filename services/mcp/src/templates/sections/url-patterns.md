### URL patterns

PostHog app links must be full URLs (origin + path) — bare paths aren't clickable in MCP clients like Cursor or Claude Desktop. Use Markdown with descriptive anchor text, e.g. `[Cohorts](https://us.posthog.com/project/1/cohorts)`. Never include `/-/`.

- If a tool result has a `*url` field (e.g. `_posthogUrl`), surface it verbatim — never rewrite or strip it.
- Otherwise build the link from the Base URL in the active-environment block (don't double-prefix):
  - Project-scoped paths → Base URL + `/project/:id`: `/settings/<section-id>` (hyphenated, e.g. `/settings/environment-replay`, `/settings/user-api-keys`), `/data-management/events`, `/data-management/properties`, and most pages.
  - Org-/account-level paths → Base URL only (no `/project/:id`): first segment `organization`, `me`, `account`, or `instance` — e.g. billing is `/organization/billing`.
