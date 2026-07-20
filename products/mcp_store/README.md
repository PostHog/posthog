# MCP store

A curated catalog of MCP servers that PostHog users can install with one click, plus support for custom per-team installations.

## Server icons (logo.dev)

Catalog icons are not committed image assets.
Each `MCPServerTemplate` carries an `icon_domain` (the vendor's brand domain, e.g. `linear.app`), and the frontend renders it through the authenticated proxy endpoint `GET /api/projects/:team_id/mcp_servers/icon/?domain=<domain>`.
The proxy fetches the brand icon from [logo.dev](https://logo.dev) via the egress-gated `CDPIconsService` and caches the response for a day.
Custom installations without a template derive a best-effort brand domain from their server URL.

### Self-hosted instances

Icon resolution requires the `LOGO_DEV_TOKEN` environment variable (a logo.dev API token) and outbound network access to `img.logo.dev`.
Without the token, which is the default on self-hosted and air-gapped deployments, the icon endpoint returns 404 and the UI falls back to a generic server glyph for every server.
This is cosmetic only: installing and using MCP servers works exactly the same without icons.
To get brand icons on a self-hosted instance, create a logo.dev account, generate an API token, and set `LOGO_DEV_TOKEN` in the environment of the web service.
