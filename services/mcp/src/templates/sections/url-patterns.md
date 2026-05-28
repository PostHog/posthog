### URL patterns

PostHog app URLs must be full URLs that include the origin and the `/project/:id/` prefix — bare paths are not clickable in MCP clients like Cursor or Claude Desktop. Never include `/-/` in URLs.

- When a tool result includes `_posthogUrl` (or any other field whose name ends in `url`), surface it to the user verbatim. Do not strip the origin or the `/project/:id/` prefix.
- When constructing a link to a PostHog page that isn't returned by a tool, prefix the path with the project base URL given in the active-environment block (e.g. `https://us.posthog.com/project/1`).
- Use Markdown with descriptive anchor text, for example `[Cohorts view](https://us.posthog.com/project/1/cohorts)`.

Key URL paths (to be combined with the project base URL):

- Settings: `/settings/<section-id>` where section IDs use hyphens, e.g. `/settings/organization-members`, `/settings/environment-replay`, `/settings/user-api-keys`
- Data management: `/data-management/events`, `/data-management/properties`
- Billing: `/organization/billing`
