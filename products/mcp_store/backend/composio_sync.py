"""Sync Composio's managed-auth toolkits into `MCPServerTemplate` rows.

This is deliberately unlike `catalog_sync`, and the difference is a trust argument rather than a
style choice. The direct catalog is code because merging an entry there is a vendor-identity
decision no probe can make: the reviewer confirms a URL really belongs to the named vendor.
Composio toolkits carry no such decision — we are not pointing agents at a vendor endpoint, we
are pointing them at Composio, and that single trust decision was made once when the integration
shipped. Hand-copying a thousand toolkits into `catalog.py` would add churn, not review value.

Only toolkits Composio can authenticate with its own OAuth apps are synced. The rest would need
us to register an app per vendor, which is the very cost this integration exists to avoid.
Toolkits already served directly are skipped so the direct server keeps winning — it speaks real
MCP rather than a proxied tool list.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import structlog

from .catalog import MCP_SERVER_CATALOG
from .composio import COMPOSIO_HUB_NAME, COMPOSIO_HUB_URL, ToolkitInfo, composio_enabled, list_managed_toolkits
from .models import MCPServerTemplate, normalize_mcp_icon_domain

logger = structlog.get_logger(__name__)

TOOLKIT_URL_PREFIX = "https://composio.dev/toolkits/"

# Composio's category vocabulary is much finer than ours; anything unmapped lands in "business",
# which is where the long tail (CRM, accounting, support desks) mostly belongs.
_CATEGORY_MAP: dict[str, str] = {
    "developer tools": "dev",
    "version control": "dev",
    "error tracking": "dev",
    "monitoring": "infra",
    "infrastructure": "infra",
    "cloud storage": "infra",
    "databases": "data",
    "analytics": "data",
    "spreadsheets": "data",
    "business intelligence": "data",
    "images & design": "design",
    "design": "design",
    "video": "design",
    "documents": "productivity",
    "team collaboration": "productivity",
    "team chat": "productivity",
    "project management": "productivity",
    "task management": "productivity",
    "productivity": "productivity",
    "scheduling & booking": "productivity",
    "video conferencing": "productivity",
    "email": "productivity",
    "file management & storage": "productivity",
    "note taking": "productivity",
}


@dataclass
class ComposioSyncCounts:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0
    skipped_direct: int = 0


def _toolkit_url(slug: str) -> str:
    return f"{TOOLKIT_URL_PREFIX}{slug}"


def _category_for(toolkit: ToolkitInfo) -> str:
    for category in toolkit.categories:
        mapped = _CATEGORY_MAP.get(category.lower())
        if mapped:
            return mapped
    return "business"


def _icon_domain_for(toolkit: ToolkitInfo) -> str:
    """Composio hands us the app's own URL, which is close enough to the brand domain the logo.dev
    proxy keys on that Composio-backed cards render with the same icons as direct ones. Marketing
    subdomains are stripped because logo.dev keys on the bare brand domain."""
    if not toolkit.app_url:
        return ""
    host = normalize_mcp_icon_domain(urlparse(toolkit.app_url).netloc or toolkit.app_url)
    for prefix in ("www.", "about.", "console.", "app.", "my."):
        if host.startswith(prefix):
            return host[len(prefix) :]
    return host


# Toolkits PostHog already serves, which must never appear as a Composio card. Deliberately an
# explicit list keyed on Composio's slug rather than inferred from names or domains: the two
# vocabularies don't line up (Composio's `app_url` for Notion is notion.so while our icon domain is
# notion.com; `jira` and `confluence` are both our single "Atlassian" entry), and a silent miss ships
# a duplicate to every tenant. Reviewing an addition here is the same judgment as adding to
# `catalog.py`, so it belongs in code where a reviewer sees it.
SERVED_ELSEWHERE: dict[str, str] = {
    # Direct MCP servers in catalog.py. These speak real MCP, so they beat a proxied tool list.
    "bitbucket": "catalog: GitLab/Atlassian family",
    "box": "catalog: Box",
    "confluence": "catalog: Atlassian",
    "figma": "catalog: Figma",
    "gitlab": "catalog: GitLab",
    "hubspot": "catalog: HubSpot",
    "jira": "catalog: Atlassian",
    "notion": "catalog: Notion",
    "prisma": "catalog: Prisma",
    # Composio splits Slack into a user toolkit and a bot toolkit; our direct Slack server covers
    # both, and the name doesn't match so the safety net misses it.
    "slackbot": "catalog: Slack",
    # First-class PostHog integrations that already give agents tools for this app. GitHub is the
    # load-bearing one: self-driving opens pull requests through it, so a second, Composio-mediated
    # GitHub would split credentials across two connections for the same work.
    "github": "integration: GitHub",
}


def _excluded_reason(toolkit: ToolkitInfo) -> str | None:
    if reason := SERVED_ELSEWHERE.get(toolkit.slug):
        return reason
    # Safety net for catalog entries whose name matches exactly; the explicit map above is what
    # catches the ones where names or domains diverge.
    if toolkit.name.strip().lower() in _direct_catalog_names():
        return "catalog: name match"
    return None


def _direct_catalog_names() -> set[str]:
    return {entry.name.strip().lower() for entry in MCP_SERVER_CATALOG}


def ensure_hub_template() -> MCPServerTemplate:
    """The template behind the one installation that carries a user's Composio connections."""
    template, created = MCPServerTemplate.objects.get_or_create(
        url=COMPOSIO_HUB_URL,
        defaults={
            "name": COMPOSIO_HUB_NAME,
            "description": "Apps you've connected to PostHog agents.",
            "auth_type": "oauth",
            "category": "business",
            "provider": "composio",
            "icon_domain": "",
            "is_active": True,
        },
    )
    if not created and not template.is_active:
        template.is_active = True
        template.save(update_fields=["is_active", "updated_at"])
    return template


def sync_composio_toolkits(*, dry_run: bool = False) -> ComposioSyncCounts:
    counts = ComposioSyncCounts()
    if not composio_enabled():
        logger.info("Composio not configured; skipping toolkit sync")
        return counts

    toolkits = list_managed_toolkits()
    existing = {t.url: t for t in MCPServerTemplate.objects.filter(provider="composio")}
    seen_urls = {COMPOSIO_HUB_URL}

    if not dry_run:
        ensure_hub_template()

    for toolkit in toolkits:
        if reason := _excluded_reason(toolkit):
            counts.skipped_direct += 1
            logger.debug("Skipping Composio toolkit already served", toolkit=toolkit.slug, reason=reason)
            continue

        icon_domain = _icon_domain_for(toolkit)
        url = _toolkit_url(toolkit.slug)
        seen_urls.add(url)
        fields = {
            "name": toolkit.name,
            "description": toolkit.description[:500],
            "auth_type": "oauth",
            "category": _category_for(toolkit),
            "icon_domain": icon_domain,
            "provider": "composio",
            "composio_toolkit_slug": toolkit.slug,
            "docs_url": toolkit.app_url,
        }
        template = existing.get(url)
        if template is None:
            counts.created += 1
            if not dry_run:
                # Born active: there is no endpoint to probe, and the trust decision is Composio's
                # managed auth config rather than this row's URL.
                MCPServerTemplate.objects.create(url=url, is_active=True, **fields)
            continue

        changed = [field for field, value in fields.items() if getattr(template, field) != value]
        if not changed:
            counts.unchanged += 1
            continue
        counts.updated += 1
        if not dry_run:
            for field, value in fields.items():
                setattr(template, field, value)
            template.save(update_fields=[*fields, "updated_at"])

    # A toolkit Composio stops offering under managed auth can no longer be connected, so leaving
    # its card installable would dead-end the user. Deactivate rather than delete: existing
    # connections keep resolving their template for name and icon.
    for url, template in existing.items():
        if url in seen_urls or not template.is_active:
            continue
        counts.deactivated += 1
        if not dry_run:
            template.is_active = False
            template.save(update_fields=["is_active", "updated_at"])

    logger.info(
        "Composio toolkit sync complete",
        created=counts.created,
        updated=counts.updated,
        unchanged=counts.unchanged,
        deactivated=counts.deactivated,
        skipped_direct=counts.skipped_direct,
        dry_run=dry_run,
    )
    return counts
