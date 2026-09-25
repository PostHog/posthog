"""Sync the code-defined catalog (``catalog.py``) into ``MCPServerTemplate`` rows.

Semantics, chosen so the sync can run unattended at every app startup:

- Rows are keyed on ``url``. A catalog entry with no row **creates** one; an entry with an
  existing row **updates content fields only**. A changed ``url`` is therefore a new identity:
  the sync creates a fresh row and leaves the old row — and installations pointing at it —
  untouched. Retire the old row by deactivating it in admin; the sync logs a warning for every
  *active* row with no catalog entry so an orphaned row can't linger unnoticed.
- The sync normally preserves operational state: ``is_active`` after creation,
  ``oauth_credentials`` (operator-provisioned shared client creds), or ``oauth_metadata``
  once set. Rows absent from the catalog (admin-added or removed entries) are left alone.
  Three fail-closed exceptions deactivate active rows: an ``auth_type`` flip, a catalog
  entry marked ``disabled``, or a DCR entry whose re-probe shows the server refusing to
  register a client for us. Entries with a catalog-managed credential source also follow
  that source: sync probes and activates them when configured, and deactivates them when
  their required settings are absent.
- **Activation gate**: a newly created entry is probed live (``probe.probe_mcp_server``)
  and born active only when the probe passes for the auth model the catalog declares —
  DCR OAuth servers must complete a real client registration and serve an authorization
  page; API-key servers must complete the MCP handshake without credentials. An API-key
  server that auth-walls the handshake (the common case) yields no MCP evidence, so it
  is born inactive for an operator to vet and activate in admin. Other servers needing
  shared OAuth credentials remain inactive until an operator provisions them. Probes run
  on creation, while a catalog-managed shared client is inactive or first adopts its
  credential source, and on an interval for an active DCR entry. A DCR probe mints a real
  client with the provider, so ``last_probed_at`` keeps it to one probe per entry per
  ``DCR_REPROBE_INTERVAL``. A re-probe only ever deactivates on refused registration, never
  on an unreachable server: the entry must not flap on a timeout or a provider fault.

  The probe is a liveness and protocol check, not a security control: it catches a dead
  url or a mis-declared auth model, but a malicious server passes it trivially. Vendor
  identity is established by human review of the ``catalog.py`` PR (CODEOWNERS-gated),
  not by anything in this module.
"""

from dataclasses import dataclass, replace
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

import structlog

from .catalog import MCP_SERVER_CATALOG, CatalogEntry
from .models import MCPServerTemplate
from .oauth_credentials import resolve_oauth_credentials_source
from .probe import ProbeResult, probe_mcp_server

logger = structlog.get_logger(__name__)

DCR_REPROBE_INTERVAL = timedelta(hours=24)

_CONTENT_FIELDS = (
    "name",
    "description",
    "auth_type",
    "category",
    "icon_domain",
    "docs_url",
    "oauth_scope_allowlist",
    "oauth_credentials_source",
)


def _entry_field_value(entry: CatalogEntry, field: str) -> object:
    value = getattr(entry, field)
    if field == "oauth_scope_allowlist" and value is not None:
        return list(value)
    if field == "oauth_credentials_source":
        return value or ""
    return value


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
    if entry.oauth_credentials_source:
        return probe.auth_flavor == "oauth_shared"
    return probe.auth_flavor == "oauth_dcr"


def _shared_client_id(entry: CatalogEntry) -> str | None:
    if not entry.oauth_credentials_source:
        return None
    credentials = resolve_oauth_credentials_source(entry.oauth_credentials_source)
    if not credentials["client_id"] or not credentials["client_secret"]:
        return None
    return credentials["client_id"]


def _probe_entry(entry: CatalogEntry) -> ProbeResult:
    return probe_mcp_server(
        entry.url,
        scope_allowlist=entry.oauth_scope_allowlist,
        shared_client_id=_shared_client_id(entry),
    )


def _dcr_reprobe_due(template: MCPServerTemplate, entry: CatalogEntry) -> bool:
    if entry.auth_type != "oauth" or entry.oauth_credentials_source or not template.is_active:
        return False
    return template.last_probed_at is None or timezone.now() - template.last_probed_at >= DCR_REPROBE_INTERVAL


def _claim_reprobe(template: MCPServerTemplate) -> bool:
    """Take the re-probe slot with a conditional update, so two overlapping syncs mint one
    client between them instead of one each."""
    now = timezone.now()
    if not MCPServerTemplate.objects.filter(pk=template.pk, last_probed_at=template.last_probed_at).update(
        last_probed_at=now
    ):
        return False
    template.last_probed_at = now
    return True


def _apply_probe_metadata(template: MCPServerTemplate, probe: ProbeResult) -> list[str]:
    changed: list[str] = []
    if probe.oauth_metadata:
        if template.oauth_metadata != probe.oauth_metadata:
            template.oauth_metadata = probe.oauth_metadata
            changed.append("oauth_metadata")
        issuer = probe.oauth_metadata.get("issuer", "")
        if issuer and template.oauth_issuer_url != issuer:
            template.oauth_issuer_url = issuer
            changed.append("oauth_issuer_url")
    return changed


def _apply_probe(template: MCPServerTemplate, entry: CatalogEntry, probe: ProbeResult, counts: SyncCounts) -> list[str]:
    template.last_probed_at = timezone.now()
    changed: list[str] = ["last_probed_at", *_apply_probe_metadata(template, probe)]
    if _activation_allowed(entry, probe):
        if not template.is_active:
            template.is_active = True
            changed.append("is_active")
            counts.activated += 1
    elif template.is_active:
        template.is_active = False
        changed.append("is_active")
    return changed


def _create_template(entry: CatalogEntry, skip_probe: bool, counts: SyncCounts) -> None:
    template = MCPServerTemplate.objects.create(
        name=entry.name,
        url=entry.url,
        description=entry.description,
        auth_type=entry.auth_type,
        category=entry.category,
        icon_domain=entry.icon_domain,
        docs_url=entry.docs_url,
        oauth_scope_allowlist=_entry_field_value(entry, "oauth_scope_allowlist"),
        oauth_credentials_source=entry.oauth_credentials_source or "",
        is_active=False,
    )
    counts.created += 1
    if skip_probe or entry.disabled:
        return

    probe = _probe_entry(entry)
    update_fields = _apply_probe(template, entry, probe, counts)
    if not template.is_active:
        logger.warning(
            "mcp_catalog_sync.created_inactive",
            url=entry.url,
            auth_flavor=probe.auth_flavor,
            probe_errors=probe.errors,
        )
    if update_fields:
        template.save(update_fields=[*update_fields, "updated_at"])


def _reprobe_dcr_entry(template: MCPServerTemplate, entry: CatalogEntry) -> list[str]:
    probe = _probe_entry(entry)
    changed = _apply_probe_metadata(template, probe)
    if probe.dcr_registration_refused:
        template.is_active = False
        changed.append("is_active")
        logger.warning(
            "mcp_catalog_sync.deactivated_dcr_refused",
            url=entry.url,
            probe_errors=probe.errors,
        )
    return changed


def _update_template(template: MCPServerTemplate, entry: CatalogEntry, skip_probe: bool, counts: SyncCounts) -> None:
    changed = [f for f in _CONTENT_FIELDS if getattr(template, f) != _entry_field_value(entry, f)]
    for f in changed:
        setattr(template, f, _entry_field_value(entry, f))
    if entry.disabled:
        if template.is_active:
            template.is_active = False
            changed.append("is_active")
            logger.warning("mcp_catalog_sync.deactivated_disabled_entry", url=entry.url)
    elif "auth_type" in changed and template.is_active:
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
    elif entry.oauth_credentials_source:
        shared_client_id = _shared_client_id(entry)
        needs_probe = shared_client_id is not None and (
            not template.is_active or not template.oauth_metadata or "oauth_credentials_source" in changed
        )
        if needs_probe and not skip_probe:
            changed += [
                field for field in _apply_probe(template, entry, _probe_entry(entry), counts) if field not in changed
            ]
        elif shared_client_id is None and template.is_active:
            template.is_active = False
            changed.append("is_active")
            logger.warning(
                "mcp_catalog_sync.deactivated_missing_credential_source",
                url=entry.url,
                oauth_credentials_source=entry.oauth_credentials_source,
            )
    elif not skip_probe and _dcr_reprobe_due(template, entry) and _claim_reprobe(template):
        changed += _reprobe_dcr_entry(template, entry)
    if not changed:
        counts.unchanged += 1
        return
    template.save(update_fields=[*changed, "updated_at"])
    counts.updated += 1


def _entry_for_environment(entry: CatalogEntry, template: MCPServerTemplate | None) -> CatalogEntry:
    if entry.oauth_credentials_source != "slack_app" or entry.url != "https://mcp.slack.com/mcp":
        return entry
    dev_enabled = bool(settings.MCP_STORE_SLACK_DEV_ALLOWED_TEAM_IDS)
    dev_template = template is not None and template.oauth_credentials_source == "slack_dev_app"
    if not dev_enabled and (not dev_template or (template is not None and not template.installations.exists())):
        return entry
    if template is not None and not dev_template and template.installations.exists():
        raise ValueError("Disconnect existing Slack MCP installations before changing OAuth apps")
    return replace(
        entry,
        name="Slack via PostHog (dev)",
        description="Search public Slack channels with the internal PostHog development app.",
        oauth_credentials_source="slack_dev_app",
        disabled=not dev_enabled,
    )


def sync_mcp_catalog(entries: list[CatalogEntry] | None = None, skip_probe: bool = False) -> SyncCounts:
    counts = SyncCounts()
    catalog = entries if entries is not None else MCP_SERVER_CATALOG
    for entry in catalog:
        try:
            template = MCPServerTemplate.objects.filter(url=entry.url).first()
            entry = _entry_for_environment(entry, template)
            if template is None:
                try:
                    _create_template(entry, skip_probe, counts)
                except IntegrityError:
                    # Lost a create race (unique url) — the winner owns creation+probe.
                    counts.unchanged += 1
            else:
                _update_template(template, entry, skip_probe, counts)
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
