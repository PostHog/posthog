"""The curated MCP server catalog, as code.

Each entry here becomes (or updates) an ``MCPServerTemplate`` row via the
``sync_mcp_server_templates`` management command, which runs on app startup in every
environment — adding a server to the store is a PR to this file, not a data migration.

The catalog owns a template's *content* (name, description, category, icon_domain,
docs_url, auth_type). Operational state — ``is_active`` after creation, and the
``oauth_credentials`` an operator provisions for servers without Dynamic Client
Registration — lives on the row and is never touched by the sync. See
``catalog_sync.py`` for the exact semantics, including the probe-gated activation
of newly created entries.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    url: str
    description: str
    auth_type: str  # "oauth" | "api_key" — must match AUTH_TYPE_CHOICES on the model
    category: str  # one of CATEGORY_CHOICES on the model
    icon_domain: str  # the vendor's brand domain, rendered via the logo.dev proxy
    docs_url: str = ""


MCP_SERVER_CATALOG: list[CatalogEntry] = [
    CatalogEntry(
        name="Atlassian",
        url="https://mcp.atlassian.com/v1/mcp",
        description="Integrate with Atlassian products like Jira and Confluence.",
        auth_type="oauth",
        category="productivity",
        icon_domain="atlassian.com",
    ),
    CatalogEntry(
        name="Box",
        url="https://mcp.box.com",
        description="Search and manage Box content with Box AI-powered Q&A and extraction.",
        auth_type="oauth",
        category="productivity",
        icon_domain="box.com",
    ),
    CatalogEntry(
        name="Browserbase",
        url="https://mcp.browserbase.com/mcp",
        description="Run cloud browser automation, screenshots, and page extraction.",
        auth_type="api_key",
        category="dev",
        icon_domain="browserbase.com",
    ),
    CatalogEntry(
        name="Cisco ThousandEyes",
        url="https://api.thousandeyes.com/mcp",
        description="Query ThousandEyes network intelligence and internet performance data.",
        auth_type="api_key",
        category="infra",
        icon_domain="thousandeyes.com",
    ),
    CatalogEntry(
        name="Circle",
        url="https://api.circle.com/v1/codegen/mcp",
        description="Build on Circle stablecoin, wallet, and payment infrastructure.",
        auth_type="api_key",
        category="business",
        icon_domain="circle.com",
    ),
    CatalogEntry(
        name="Clerk",
        url="https://mcp.clerk.com/mcp",
        description="Retrieve Clerk authentication setup guides and SDK context.",
        auth_type="api_key",
        category="dev",
        icon_domain="clerk.com",
    ),
    CatalogEntry(
        name="ClickHouse",
        url="https://mcp.clickhouse.cloud/mcp",
        description="Query ClickHouse Cloud databases, schemas, and analytics.",
        auth_type="oauth",
        category="data",
        icon_domain="clickhouse.com",
    ),
    CatalogEntry(
        name="Cloudflare",
        url="https://mcp.cloudflare.com/mcp",
        description="Manage Cloudflare Workers, Durable Objects, and platform resources.",
        auth_type="oauth",
        category="infra",
        icon_domain="cloudflare.com",
    ),
    CatalogEntry(
        name="Context7",
        url="https://mcp.context7.com/mcp",
        description="Retrieve up-to-date developer documentation for libraries and frameworks.",
        auth_type="api_key",
        category="dev",
        icon_domain="context7.com",
    ),
    CatalogEntry(
        name="Datadog",
        url="https://mcp.datadoghq.com/api/unstable/mcp-server/mcp",
        description="Query Datadog logs, metrics, traces, and dashboards.",
        auth_type="oauth",
        category="infra",
        icon_domain="datadoghq.com",
    ),
    CatalogEntry(
        name="dbt Labs",
        url="https://cloud.getdbt.com/api/ai/v1/mcp/",
        description="Work with dbt data modeling, transformations, and project workflows.",
        auth_type="oauth",
        category="data",
        icon_domain="getdbt.com",
    ),
    CatalogEntry(
        name="Figma",
        url="https://mcp.figma.com/mcp",
        description="Work with Figma design files, dev handoff, and design-to-code context.",
        auth_type="oauth",
        category="design",
        icon_domain="figma.com",
    ),
    CatalogEntry(
        name="Firetiger",
        url="https://api.cloud.firetiger.com/mcp/v1",
        description="Run Firetiger telemetry queries, investigations, and observability automation.",
        auth_type="oauth",
        category="infra",
        icon_domain="firetiger.com",
    ),
    CatalogEntry(
        name="GitLab",
        url="https://gitlab.com/api/v4/mcp",
        description="Manage GitLab issues, merge requests, pipelines, and repos.",
        auth_type="oauth",
        category="dev",
        icon_domain="gitlab.com",
    ),
    CatalogEntry(
        name="Hex",
        url="https://app.hex.tech/mcp",
        description="Search Hex workspaces, notebooks, and data analysis collaboration.",
        auth_type="oauth",
        category="data",
        icon_domain="hex.tech",
    ),
    CatalogEntry(
        name="HubSpot",
        url="https://mcp.hubspot.com",
        description="Manage HubSpot contacts, companies, and deals.",
        auth_type="oauth",
        category="business",
        icon_domain="hubspot.com",
    ),
    CatalogEntry(
        name="LaunchDarkly",
        url="https://mcp.launchdarkly.com/mcp/fm",
        description="Manage LaunchDarkly feature flags and release controls.",
        auth_type="oauth",
        category="dev",
        icon_domain="launchdarkly.com",
    ),
    CatalogEntry(
        name="Neon",
        url="https://mcp.neon.tech/mcp",
        description="Manage Neon serverless Postgres projects, branches, and databases.",
        auth_type="oauth",
        category="data",
        icon_domain="neon.tech",
    ),
    CatalogEntry(
        name="Notion",
        url="https://mcp.notion.com/mcp",
        description="Search and manage Notion pages, databases, and knowledge base content.",
        auth_type="oauth",
        category="productivity",
        icon_domain="notion.com",
    ),
    CatalogEntry(
        name="PagerDuty",
        url="https://mcp.pagerduty.com/mcp",
        description="Manage PagerDuty incidents, services, schedules, and on-call rotations.",
        auth_type="api_key",
        category="infra",
        icon_domain="pagerduty.com",
    ),
    CatalogEntry(
        name="PlanetScale",
        url="https://mcp.pscale.dev/mcp/planetscale",
        description="Manage PlanetScale databases, branches, schemas, and insights.",
        auth_type="oauth",
        category="data",
        icon_domain="planetscale.com",
    ),
    CatalogEntry(
        name="Postman",
        url="https://mcp.postman.com/mcp",
        description="Manage Postman collections, tests, mocks, and API lifecycle workflows.",
        auth_type="oauth",
        category="dev",
        icon_domain="postman.com",
    ),
    CatalogEntry(
        name="Prisma",
        url="https://mcp.prisma.io/mcp",
        description="Manage Prisma Postgres databases and ORM workflows.",
        auth_type="oauth",
        category="data",
        icon_domain="prisma.io",
    ),
    CatalogEntry(
        name="Render",
        url="https://mcp.render.com/mcp",
        description="Deploy, debug, and monitor applications on Render.",
        auth_type="api_key",
        category="infra",
        icon_domain="render.com",
    ),
    CatalogEntry(
        name="Sanity",
        url="https://mcp.sanity.io/mcp",
        description="Work with Sanity content studio, schemas, and structured content.",
        auth_type="oauth",
        category="design",
        icon_domain="sanity.io",
    ),
    CatalogEntry(
        name="Semgrep",
        url="https://mcp.semgrep.ai/mcp",
        description="Run Semgrep static analysis and security scans.",
        auth_type="oauth",
        category="dev",
        icon_domain="semgrep.dev",
    ),
    CatalogEntry(
        name="Sentry",
        url="https://mcp.sentry.dev/mcp",
        description="Inspect Sentry errors, traces, issues, and release context.",
        auth_type="oauth",
        category="dev",
        icon_domain="sentry.io",
    ),
    CatalogEntry(
        name="Slack",
        url="https://mcp.slack.com/mcp",
        description="Search Slack channels, send messages, and access workspace context.",
        auth_type="oauth",
        category="productivity",
        icon_domain="slack.com",
    ),
    CatalogEntry(
        name="Sourcegraph",
        url="https://sourcegraph.com/.api/mcp/v1",
        description="Search code and retrieve code intelligence across repos.",
        auth_type="oauth",
        category="dev",
        icon_domain="sourcegraph.com",
    ),
    CatalogEntry(
        name="Stripe",
        url="https://mcp.stripe.com",
        description="Manage Stripe payments, billing, and API integration context.",
        auth_type="oauth",
        category="business",
        icon_domain="stripe.com",
    ),
    CatalogEntry(
        name="Supabase",
        url="https://mcp.supabase.com/mcp",
        description="Manage Supabase projects, databases, and branches.",
        auth_type="oauth",
        category="data",
        icon_domain="supabase.com",
    ),
    CatalogEntry(
        name="Svelte",
        url="https://mcp.svelte.dev/mcp",
        description="Access Svelte docs and framework development workflows.",
        auth_type="oauth",
        category="dev",
        icon_domain="svelte.dev",
    ),
    CatalogEntry(
        name="ThoughtSpot",
        url="https://agent.thoughtspot.app/mcp",
        description="Search ThoughtSpot developer docs and embedded analytics APIs.",
        auth_type="oauth",
        category="data",
        icon_domain="thoughtspot.com",
    ),
    CatalogEntry(
        name="Wix",
        url="https://mcp.wix.com/mcp",
        description="Manage Wix sites, apps, and dashboard extensions.",
        auth_type="oauth",
        category="design",
        icon_domain="wix.com",
    ),
]
