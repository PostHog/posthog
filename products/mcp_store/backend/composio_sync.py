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
    """Composio hands us the app's own URL, which is exactly the brand domain the logo.dev proxy
    keys on, so Composio-backed cards render with the same icons as direct ones."""
    if not toolkit.app_url:
        return ""
    return normalize_mcp_icon_domain(urlparse(toolkit.app_url).netloc or toolkit.app_url)


def _directly_served_domains() -> set[str]:
    return {normalize_mcp_icon_domain(entry.icon_domain) for entry in MCP_SERVER_CATALOG if entry.icon_domain}


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
    direct_domains = _directly_served_domains()
    existing = {t.url: t for t in MCPServerTemplate.objects.filter(provider="composio")}
    seen_urls = {COMPOSIO_HUB_URL}

    if not dry_run:
        ensure_hub_template()

    for toolkit in toolkits:
        icon_domain = _icon_domain_for(toolkit)
        if icon_domain and icon_domain in direct_domains:
            counts.skipped_direct += 1
            continue

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
