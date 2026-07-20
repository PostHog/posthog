"""Sync the code-defined catalog (``catalog.py``) into ``MCPServerTemplate`` rows.

Semantics, chosen so the sync can run unattended at every app startup:

- Rows are keyed on ``url``. A catalog entry with no row **creates** one; an entry with an
  existing row **updates content fields only** (name, description, auth_type, category,
  icon_domain, docs_url).
- The sync never touches operational state: ``is_active`` after creation,
  ``oauth_credentials`` (operator-provisioned shared client creds), or ``oauth_metadata``
  once set. Rows absent from the catalog (admin-added or removed entries) are left alone.
- **Activation gate**: a newly created entry is probed live (``probe.probe_mcp_server``)
  and born active only when the probe passes for the auth model the catalog declares —
  DCR OAuth servers must complete a real client registration and serve an authorization
  page; API-key/open servers must speak the MCP handshake. Servers needing shared OAuth
  credentials are always born inactive: an operator provisions credentials in admin and
  activates. Probes run only on creation — a DCR probe mints a real client on the
  provider, so re-probing every sync cycle would leak registrations.
"""

from dataclasses import dataclass

from django.db import IntegrityError

import structlog

from .catalog import MCP_SERVER_CATALOG, CatalogEntry
from .models import MCPServerTemplate
from .probe import ProbeResult, probe_mcp_server

logger = structlog.get_logger(__name__)

_CONTENT_FIELDS = ("name", "description", "auth_type", "category", "icon_domain", "docs_url")


@dataclass
class SyncCounts:
    created: int = 0
    activated: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0


def _activation_allowed(entry: CatalogEntry, probe: ProbeResult) -> bool:
    """The probe must pass *and* agree with the auth model the catalog declares — a probe
    that classifies an "api_key" entry as OAuth (or vice versa) means the entry is wrong,
    not that the server is ready for users."""
    if not probe.passed_activation_gate:
        return False
    if entry.auth_type == "api_key":
        return probe.auth_flavor in ("open", "api_key_or_unknown")
    return probe.auth_flavor == "oauth_dcr"


def _create_template(entry: CatalogEntry, skip_probe: bool, counts: SyncCounts) -> None:
    template = MCPServerTemplate.objects.create(
        name=entry.name,
        url=entry.url,
        description=entry.description,
        auth_type=entry.auth_type,
        category=entry.category,
        icon_domain=entry.icon_domain,
        docs_url=entry.docs_url,
        is_active=False,
    )
    counts.created += 1
    if skip_probe:
        return

    probe = probe_mcp_server(entry.url)
    update_fields = []
    if probe.oauth_metadata and not template.oauth_metadata:
        # Persisting discovered metadata saves the operator the admin "discover metadata"
        # step for shared-creds servers; DCR installs discover fresh per install anyway.
        template.oauth_metadata = probe.oauth_metadata
        issuer = probe.oauth_metadata.get("issuer", "")
        if issuer:
            template.oauth_issuer_url = issuer
        update_fields += ["oauth_metadata", "oauth_issuer_url"]
    if _activation_allowed(entry, probe):
        template.is_active = True
        update_fields.append("is_active")
        counts.activated += 1
    else:
        logger.info(
            "mcp_catalog_sync.created_inactive",
            url=entry.url,
            auth_flavor=probe.auth_flavor,
            probe_errors=probe.errors,
        )
    if update_fields:
        template.save(update_fields=[*update_fields, "updated_at"])


def _update_template(template: MCPServerTemplate, entry: CatalogEntry, counts: SyncCounts) -> None:
    changed = [f for f in _CONTENT_FIELDS if getattr(template, f) != getattr(entry, f)]
    if not changed:
        counts.unchanged += 1
        return
    for f in changed:
        setattr(template, f, getattr(entry, f))
    template.save(update_fields=[*changed, "updated_at"])
    counts.updated += 1


def sync_mcp_catalog(entries: list[CatalogEntry] | None = None, skip_probe: bool = False) -> SyncCounts:
    counts = SyncCounts()
    for entry in entries if entries is not None else MCP_SERVER_CATALOG:
        try:
            template = MCPServerTemplate.objects.filter(url=entry.url).first()
            if template is None:
                try:
                    _create_template(entry, skip_probe, counts)
                except IntegrityError:
                    # Lost a create race (unique url) — the winner owns creation+probe.
                    counts.unchanged += 1
            else:
                _update_template(template, entry, counts)
        except Exception:
            logger.exception("mcp_catalog_sync.entry_failed", url=entry.url)
            counts.failed += 1
    logger.info(
        "mcp_catalog_sync.done",
        created=counts.created,
        activated=counts.activated,
        updated=counts.updated,
        unchanged=counts.unchanged,
        failed=counts.failed,
    )
    return counts
