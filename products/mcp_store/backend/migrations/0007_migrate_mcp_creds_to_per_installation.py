from django.db import migrations

# The curated set of MCP servers we seed as inactive templates.
CURATED_TEMPLATES = [
    {
        "name": "Atlassian",
        "url": "https://mcp.atlassian.com/v1/mcp",
        "description": "Integrate with Atlassian products like Jira and Confluence.",
        "auth_type": "oauth",
    },
    {
        "name": "Box",
        "url": "https://mcp.box.com",
        "description": "Search and manage Box content with Box AI-powered Q&A and extraction.",
        "auth_type": "oauth",
    },
    {
        "name": "Browserbase",
        "url": "https://mcp.browserbase.com/mcp",
        "description": "Run cloud browser automation, screenshots, and page extraction.",
        "auth_type": "api_key",
    },
    {
        "name": "Cisco ThousandEyes",
        "url": "https://api.thousandeyes.com/mcp",
        "description": "Query ThousandEyes network intelligence and internet performance data.",
        "auth_type": "api_key",
    },
    {
        "name": "Circle",
        "url": "https://api.circle.com/v1/codegen/mcp",
        "description": "Build on Circle stablecoin, wallet, and payment infrastructure.",
        "auth_type": "api_key",
    },
    {
        "name": "Clerk",
        "url": "https://mcp.clerk.com/mcp",
        "description": "Retrieve Clerk authentication setup guides and SDK context.",
        "auth_type": "api_key",
    },
    {
        "name": "ClickHouse",
        "url": "https://mcp.clickhouse.cloud/mcp",
        "description": "Query ClickHouse Cloud databases, schemas, and analytics.",
        "auth_type": "oauth",
    },
    {
        "name": "Cloudflare",
        "url": "https://mcp.cloudflare.com/mcp",
        "description": "Manage Cloudflare Workers, Durable Objects, and platform resources.",
        "auth_type": "oauth",
    },
    {
        "name": "Context7",
        "url": "https://mcp.context7.com/mcp",
        "description": "Retrieve up-to-date developer documentation for libraries and frameworks.",
        "auth_type": "api_key",
    },
    {
        "name": "Datadog",
        "url": "https://mcp.datadoghq.com/api/unstable/mcp-server/mcp",
        "description": "Query Datadog logs, metrics, traces, and dashboards.",
        "auth_type": "oauth",
    },
    {
        "name": "dbt Labs",
        "url": "https://cloud.getdbt.com/api/ai/v1/mcp/",
        "description": "Work with dbt data modeling, transformations, and project workflows.",
        "auth_type": "oauth",
    },
    {
        "name": "Figma",
        "url": "https://mcp.figma.com/mcp",
        "description": "Work with Figma design files, dev handoff, and design-to-code context.",
        "auth_type": "oauth",
    },
    {
        "name": "Firetiger",
        "url": "https://api.cloud.firetiger.com/mcp/v1",
        "description": "Run Firetiger telemetry queries, investigations, and observability automation.",
        "auth_type": "oauth",
    },
    {
        "name": "GitLab",
        "url": "https://gitlab.com/api/v4/mcp",
        "description": "Manage GitLab issues, merge requests, pipelines, and repos.",
        "auth_type": "oauth",
    },
    {
        "name": "Hex",
        "url": "https://app.hex.tech/mcp",
        "description": "Search Hex workspaces, notebooks, and data analysis collaboration.",
        "auth_type": "oauth",
    },
    {
        "name": "LaunchDarkly",
        "url": "https://mcp.launchdarkly.com/mcp/fm",
        "description": "Manage LaunchDarkly feature flags and release controls.",
        "auth_type": "oauth",
    },
    {
        "name": "Neon",
        "url": "https://mcp.neon.tech/mcp",
        "description": "Manage Neon serverless Postgres projects, branches, and databases.",
        "auth_type": "oauth",
    },
    {
        "name": "Notion",
        "url": "https://mcp.notion.com/mcp",
        "description": "Search and manage Notion pages, databases, and knowledge base content.",
        "auth_type": "oauth",
    },
    {
        "name": "PagerDuty",
        "url": "https://mcp.pagerduty.com/mcp",
        "description": "Manage PagerDuty incidents, services, schedules, and on-call rotations.",
        "auth_type": "api_key",
    },
    {
        "name": "PlanetScale",
        "url": "https://mcp.pscale.dev/mcp/planetscale",
        "description": "Manage PlanetScale databases, branches, schemas, and insights.",
        "auth_type": "oauth",
    },
    {
        "name": "Postman",
        "url": "https://mcp.postman.com/mcp",
        "description": "Manage Postman collections, tests, mocks, and API lifecycle workflows.",
        "auth_type": "oauth",
    },
    {
        "name": "Prisma",
        "url": "https://mcp.prisma.io/mcp",
        "description": "Manage Prisma Postgres databases and ORM workflows.",
        "auth_type": "oauth",
    },
    {
        "name": "Render",
        "url": "https://mcp.render.com/mcp",
        "description": "Deploy, debug, and monitor applications on Render.",
        "auth_type": "api_key",
    },
    {
        "name": "Sanity",
        "url": "https://mcp.sanity.io/mcp",
        "description": "Work with Sanity content studio, schemas, and structured content.",
        "auth_type": "oauth",
    },
    {
        "name": "Semgrep",
        "url": "https://mcp.semgrep.ai/mcp",
        "description": "Run Semgrep static analysis and security scans.",
        "auth_type": "oauth",
    },
    {
        "name": "Sentry",
        "url": "https://mcp.sentry.dev/mcp",
        "description": "Inspect Sentry errors, traces, issues, and release context.",
        "auth_type": "oauth",
    },
    {
        "name": "Slack",
        "url": "https://mcp.slack.com/mcp",
        "description": "Search Slack channels, send messages, and access workspace context.",
        "auth_type": "oauth",
    },
    {
        "name": "Sourcegraph",
        "url": "https://sourcegraph.com/.api/mcp/v1",
        "description": "Search code and retrieve code intelligence across repos.",
        "auth_type": "oauth",
    },
    {
        "name": "Stripe",
        "url": "https://mcp.stripe.com",
        "description": "Manage Stripe payments, billing, and API integration context.",
        "auth_type": "oauth",
    },
    {
        "name": "Supabase",
        "url": "https://mcp.supabase.com/mcp",
        "description": "Manage Supabase projects, databases, and branches.",
        "auth_type": "oauth",
    },
    {
        "name": "Svelte",
        "url": "https://mcp.svelte.dev/mcp",
        "description": "Access Svelte docs and framework development workflows.",
        "auth_type": "oauth",
    },
    {
        "name": "ThoughtSpot",
        "url": "https://agent.thoughtspot.app/mcp",
        "description": "Search ThoughtSpot developer docs and embedded analytics APIs.",
        "auth_type": "oauth",
    },
    {
        "name": "Wix",
        "url": "https://mcp.wix.com/mcp",
        "description": "Manage Wix sites, apps, and dashboard extensions.",
        "auth_type": "oauth",
    },
    {
        "name": "HubSpot",
        "url": "https://mcp.hubspot.com",
        "description": "Manage HubSpot contacts, companies, and deals.",
        "auth_type": "oauth",
    },
]


def seed_templates_and_backfill_installations(apps, schema_editor):
    MCPServerTemplate = apps.get_model("mcp_store", "MCPServerTemplate")
    MCPServerInstallation = apps.get_model("mcp_store", "MCPServerInstallation")

    templates_by_url: dict[str, object] = {}
    for template_def in CURATED_TEMPLATES:
        template, _ = MCPServerTemplate.objects.get_or_create(
            url=template_def["url"],
            defaults={
                "name": template_def["name"],
                "description": template_def["description"],
                "auth_type": template_def["auth_type"],
                "icon_key": template_def["name"],
                "is_active": False,  # Activated after an operator fills in client credentials.
            },
        )
        templates_by_url[template.url] = template

    # For each existing installation, either re-point it at its curated template
    # (and force a reconnect so it stops using the shared DCR client) or migrate
    # the shared server's creds onto the installation itself.
    curated_urls = set(templates_by_url.keys())
    for installation in MCPServerInstallation.objects.select_related("server").iterator():
        sensitive = dict(installation.sensitive_configuration or {})

        if installation.url in curated_urls:
            template = templates_by_url[installation.url]
            installation.template = template
            # Clean cutover: force the user to reconnect through the shared template
            # client on next use. Their old tokens keep working until they expire;
            # at that point the refresh flips to template creds.
            if installation.auth_type == "oauth":
                sensitive["needs_reauth"] = True
            installation.sensitive_configuration = sensitive
            installation.save(update_fields=["template", "sensitive_configuration", "updated_at"])
            continue

        # Truly custom install — copy the old MCPServer's creds onto the installation
        # so each user ends up with their own per-installation DCR state.
        legacy_server = installation.server
        if legacy_server is None:
            continue
        legacy_metadata = legacy_server.oauth_metadata or {}
        legacy_client_id = legacy_server.oauth_client_id or ""

        if legacy_metadata and not installation.oauth_metadata:
            installation.oauth_metadata = dict(legacy_metadata)
        if legacy_server.url and not installation.oauth_issuer_url:
            installation.oauth_issuer_url = legacy_server.url
        if legacy_client_id:
            sensitive.setdefault("dcr_client_id", legacy_client_id)
            sensitive.setdefault("dcr_is_user_provided", False)

        installation.sensitive_configuration = sensitive
        installation.save(
            update_fields=[
                "oauth_issuer_url",
                "oauth_metadata",
                "sensitive_configuration",
                "updated_at",
            ]
        )


def reverse_noop(apps, schema_editor):
    # Data migration is one-way: we don't attempt to restore the pre-template
    # state because backfilled installations already own their creds now.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0006_mcpservertemplate_installation_fields_and_tools"),
    ]

    operations = [
        migrations.RunPython(
            seed_templates_and_backfill_installations,
            reverse_code=reverse_noop,
        ),
        # Phase 1: drop the legacy `server` FKs from Django's state only. The
        # DB columns stay (server_id on both tables) so the previous deploy
        # — which still has the field in its ORM — continues to work during
        # the rolling deploy. Phase 2 (migration 0008, follow-up PR) DROPs
        # the columns and the mcp_store_mcpserver table entirely.
        #
        # The columns are already nullable (declared null=True since 0006),
        # so new inserts from the post-this-migration code path work without
        # a DEFAULT.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="mcpserverinstallation",
                    name="server",
                ),
                migrations.RemoveField(
                    model_name="mcpoauthstate",
                    name="server",
                ),
            ],
            database_operations=[],
        ),
    ]
