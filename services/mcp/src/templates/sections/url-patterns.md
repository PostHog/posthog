### URL patterns

PostHog app links must be full URLs (origin + path) — bare paths aren't clickable in MCP clients like Cursor or Claude Desktop. Use Markdown with descriptive anchor text, e.g. `[Cohorts](https://us.posthog.com/project/1/cohorts)`. Never include `/-/`.

Choose the link source in this order:

1. If a tool result has a `*url` field (e.g. `_posthogUrl`), surface it verbatim — never rewrite or strip it.
2. Only when you actually want to link a specific entity (or the user asks for a link) and it has no `_posthogUrl`, call `generate-app-url` and surface the `url` verbatim — don't hand-write slugs or retype IDs into paths, both are easy to get wrong. Don't fetch a link just because a result has an ID.
3. Only for genuinely static pages not covered by `generate-app-url` (some settings / data-management pages), build the link from the Base URL in the active-environment block (don't double-prefix):
   - Project-scoped paths → Base URL + `/project/:id`: `/settings/<section-id>` (hyphenated, e.g. `/settings/environment-replay`, `/settings/user-api-keys`), `/data-management/events`, `/data-management/properties`.
   - Org-/account-level paths → Base URL only (no `/project/:id`): first segment `organization`, `me`, `account`, or `instance` — e.g. billing is `/organization/billing`.
