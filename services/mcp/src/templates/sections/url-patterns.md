### URL patterns

All PostHog app URLs must use relative paths without a domain (no us.posthog.com, eu.posthog.com, app.posthog.com), and omit the `/project/:id/` prefix. Never include `/-/` in URLs.
Use Markdown with descriptive anchor text, for example "[Cohorts view](/cohorts)".

Key URL patterns:

- Settings: `/settings/<section-id>` where section IDs use hyphens, e.g. `/settings/organization-members`, `/settings/environment-replay`, `/settings/user-api-keys`
- Data management: `/data-management/events`, `/data-management/properties`
- Billing: `/organization/billing`
