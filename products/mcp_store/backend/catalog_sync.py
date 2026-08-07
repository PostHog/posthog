"""Sync the code-defined catalog (``catalog.py``) into ``MCPServerTemplate`` rows.

Semantics, chosen so the sync can run unattended at every app startup:

- Rows are keyed on ``url``. A catalog entry with no row **creates** one; an entry with an
  existing row **updates content fields only** (name, description, auth_type, category,
  icon_domain, docs_url). A changed ``url`` is therefore a new identity: the sync creates a
  fresh row and leaves the old row — and installations pointing at it — untouched. Retire
  the old row by deactivating it in admin; the sync logs a warning for every *active* row
  with no catalog entry so an orphaned row can't linger unnoticed.
- The sync never touches operational state: ``is_active`` after creation,
  ``oauth_credentials`` (operator-provisioned shared client creds), or ``oauth_metadata``
  once set. Rows absent from the catalog (admin-added or removed entries) are left alone.
  One fail-closed exception: an ``auth_type`` flip on an active row deactivates it, since
  the row was vetted and activated under the old auth model — an operator re-vets and
  reactivates in admin.
- **Activation gate**: a newly created entry is probed live (``probe.probe_mcp_server``)
  and born active only when the probe passes for the auth model the catalog declares —
  DCR OAuth servers must complete a real client registration and serve an authorization
  page; API-key servers must complete the MCP handshake without credentials. An API-key
  server that auth-walls the handshake (the common case) yields no MCP evidence, so it
  is born inactive for an operator to vet and activate in admin. Servers needing shared
  OAuth credentials are always born inactive: an operator provisions credentials in
  admin and activates. Probes run only on creation — a DCR probe mints a real client on the
  provider, so re-probing every sync cycle would leak registrations.

  The probe is a liveness and protocol check, not a security control: it catches a dead
  url or a mis-declared auth model, but a malicious server passes it trivially. Vendor
  identity is established by human review of the ``catalog.py`` PR (CODEOWNERS-gated),
  not by anything in this module.
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
        # A reachable but auth-walled endpoint ("api_key_or_unknown") never passes the
        # gate — a bare 401/403 proves nothing about MCP — so agreement here means the
        # handshake completed without credentials.
        return probe.auth_flavor == "open"
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
        logger.warning(
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
    if "auth_type" in changed and template.is_active:
        # The row was vetted and activated under the old auth model — e.g. an
        # oauth→api_key flip would route new installs through the API-key branch
        # with no key provisioned. Fail closed; an operator re-vets and reactivates.
        template.is_active = False
        changed.append("is_active")
        logger.warning(
            "mcp_catalog_sync.deactivated_on_auth_type_change",
            url=entry.url,
            auth_type=entry.auth_type,
        )
    template.save(update_fields=[*changed, "updated_at"])
    counts.updated += 1


def sync_mcp_catalog(entries: list[CatalogEntry] | None = None, skip_probe: bool = False) -> SyncCounts:
    counts = SyncCounts()
    catalog = entries if entries is not None else MCP_SERVER_CATALOG
    for entry in catalog:
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
    orphaned_active = list(
        MCPServerTemplate.objects.filter(is_active=True)
        .exclude(url__in=[e.url for e in catalog])
        .values_list("url", flat=True)
    )
    if orphaned_active:
        # Either an admin-added row (consider folding it into the catalog) or a row
        # orphaned by a catalog url edit — the latter keeps serving installs forever
        # unless an operator notices and retires it.
        logger.warning("mcp_catalog_sync.active_rows_not_in_catalog", urls=orphaned_active)
    logger.info(
        "mcp_catalog_sync.done",
        created=counts.created,
        activated=counts.activated,
        updated=counts.updated,
        unchanged=counts.unchanged,
        failed=counts.failed,
    )
    return counts
