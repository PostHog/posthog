from urllib.parse import urlparse

from django.db import migrations

# Brand domains for every icon_key known to have shipped (the curated seeds from 0007 plus
# admin-added templates that had bundled frontend assets). logo.dev keys brand icons on these.
ICON_KEY_TO_DOMAIN = {
    "airops": "airops.com",
    "atlassian": "atlassian.com",
    "attio": "attio.com",
    "box": "box.com",
    "browserbase": "browserbase.com",
    "canva": "canva.com",
    "circle": "circle.com",
    "cisco_thousandeyes": "thousandeyes.com",
    "clerk": "clerk.com",
    "clickhouse": "clickhouse.com",
    "cloudflare": "cloudflare.com",
    "context7": "context7.com",
    "datadog": "datadoghq.com",
    "dbt_labs": "getdbt.com",
    "figma": "figma.com",
    "firetiger": "firetiger.com",
    "github": "github.com",
    "gitlab": "gitlab.com",
    "hex": "hex.tech",
    "hubspot": "hubspot.com",
    "launchdarkly": "launchdarkly.com",
    "linear": "linear.app",
    "monday": "monday.com",
    "neon": "neon.tech",
    "notion": "notion.com",
    "pagerduty": "pagerduty.com",
    "planetscale": "planetscale.com",
    "postman": "postman.com",
    "prisma": "prisma.io",
    "render": "render.com",
    "sanity": "sanity.io",
    "semgrep": "semgrep.dev",
    "sentry": "sentry.io",
    "slack": "slack.com",
    "sourcegraph": "sourcegraph.com",
    "stripe": "stripe.com",
    "supabase": "supabase.com",
    "svelte": "svelte.dev",
    "thoughtspot": "thoughtspot.com",
    "wix": "wix.com",
}

_STRIPPED_SUBDOMAINS = ("mcp.", "api.", "www.")


def _domain_from_server_url(server_url: str) -> str:
    host = (urlparse(server_url).hostname or "").lower()
    for prefix in _STRIPPED_SUBDOMAINS:
        if host.startswith(prefix) and host.count(".") >= 2:
            return host[len(prefix) :]
    return host


def backfill_icon_domains(apps, schema_editor) -> None:
    MCPServerTemplate = apps.get_model("mcp_store", "MCPServerTemplate")
    to_update = []
    for template in MCPServerTemplate.objects.filter(icon_domain=""):
        domain = ICON_KEY_TO_DOMAIN.get(template.icon_key) or _domain_from_server_url(template.url)
        if domain:
            template.icon_domain = domain
            to_update.append(template)
    MCPServerTemplate.objects.bulk_update(to_update, ["icon_domain"], batch_size=100)


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0013_mcpservertemplate_icon_domain"),
    ]

    operations = [
        migrations.RunPython(backfill_icon_domains, migrations.RunPython.noop, elidable=True),
    ]
