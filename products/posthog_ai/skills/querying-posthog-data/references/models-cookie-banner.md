# Cookie banner

## CookieBannerConfig (`system.cookie_banner_configs`)

The project's cookie consent banner configuration. A project has at most one banner, so this table holds zero or one rows per team.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this banner belongs to
`enabled` | boolean | NOT NULL | Whether the banner is served to the website via remote config
`appearance` | jsonb | NOT NULL | Appearance overrides: `title`, `description`, `acceptButtonText`, `declineButtonText`, `artStyle` (`none`, `posthog-logo`, `hedgehog-wave`, `hedgehog-heart`), `position` (`bottom-left`, `bottom-right`, `bottom-bar`), `backgroundColor`, `textColor`, `buttonColor`, `buttonTextColor`, `whiteLabel`
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp

### Important Notes

- `appearance` stores only user overrides; keys not present fall back to PostHog-styled defaults at delivery time
- `whiteLabel: true` in `appearance` only takes effect when the organization has the `white_labelling` entitlement — the served banner re-checks this on every remote config rebuild
- Use the `cookie-banner-create` / `cookie-banner-partial-update` MCP tools for writes
