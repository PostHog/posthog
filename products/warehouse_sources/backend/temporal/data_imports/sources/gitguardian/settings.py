from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class GitGuardianEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    # Field to partition by. Must be a STABLE detection/creation timestamp (never a mutable
    # status timestamp) so partitions aren't rewritten every sync.
    partition_key: Optional[str] = None
    # Explicit `ordering` param so pagination walks a stable monotonic field; must match the
    # endpoint's SourceResponse sort_mode (asc).
    ordering: Optional[str] = None
    # "desc" for incremental endpoints with no `ordering` param: the pipeline then promotes the
    # watermark only when the sync completes, so it never depends on the API's row order.
    sort_mode: Literal["asc", "desc"] = "asc"
    # GitGuardian caps per_page at 100. None for endpoints that take no paging params.
    page_size: Optional[int] = 100
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Scope named in permission errors when the probe can't extract the API's own detail message.
    required_scope: str = "incidents:read"
    # Safety overlap subtracted from the incremental watermark each run. GitGuardian rows are
    # created immutable but their triage fields keep mutating (incident status / resolved_at,
    # occurrence presence), and there is no updated-since filter — so we re-pull a trailing
    # window of recently detected rows to pick up late transitions. Merge dedupes on the
    # primary key. Older transitions are only recaptured by a full refresh.
    incremental_lookback: Optional[timedelta] = None
    # Only incremental-capable endpoints checkpoint resume state: their sync merges on the
    # primary key, so a resumed job re-yielding the last page dedupes cleanly. The small
    # full-refresh tables just restart from page one on a worker restart.
    resumable: bool = False
    # Fields dropped from every row before it lands in the warehouse. Used to strip bearer links
    # (e.g. `share_url`, which grants secret access without a GitGuardian account) that would
    # otherwise leak the very secrets this data is meant to help remediate.
    excluded_fields: AbstractSet[str] = field(default_factory=frozenset)
    # Fan-out: walk this parent endpoint and fetch `path` once per parent row, substituting the
    # parent's `id` into the `{parent_id}` placeholder. The probe for scope checks hits the parent
    # instead, since the child path can't be requested without a real id.
    parent_endpoint: Optional[str] = None
    # Column that receives the parent's `id` on each child row, for children whose rows don't
    # carry it themselves. Needed to keep the primary key unique across parents.
    parent_id_field: Optional[str] = None
    # Other endpoints whose scopes this table also needs; the permission probe checks each one.
    also_requires: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()


_DATE_INCREMENTAL_FIELD: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.DateTime,
        "field": "date",
        "field_type": IncrementalFieldType.DateTime,
    },
]


GITGUARDIAN_ENDPOINTS: dict[str, GitGuardianEndpointConfig] = {
    # Secret incidents: the core detection history. `date` (first detection) is immutable, and
    # the endpoint accepts a server-side `date_after` filter plus `ordering=date`, so incremental
    # sync watermarks on it. Status/resolved_at/ignored_at mutate after detection with no
    # updated-since filter, hence the trailing lookback window.
    "secret_incidents": GitGuardianEndpointConfig(
        name="secret_incidents",
        path="/v1/incidents/secrets",
        default_incremental_field="date",
        partition_key="date",
        ordering="date",
        required_scope="incidents:read",
        incremental_lookback=timedelta(days=7),
        resumable=True,
        # `share_url` is a no-auth bearer link that can expose the leaked secret itself.
        excluded_fields=frozenset({"share_url"}),
        incremental_fields=_DATE_INCREMENTAL_FIELD,
    ),
    # Secret occurrences: one row per place a secret was found (commit, file, ...). Same
    # `date_after` + `ordering=date` semantics as incidents; `presence` can flip after
    # remediation, hence the lookback.
    "secret_occurrences": GitGuardianEndpointConfig(
        name="secret_occurrences",
        path="/v1/occurrences/secrets",
        default_incremental_field="date",
        partition_key="date",
        ordering="date",
        required_scope="incidents:read",
        incremental_lookback=timedelta(days=7),
        resumable=True,
        incremental_fields=_DATE_INCREMENTAL_FIELD,
    ),
    # Monitored sources (repositories etc.): a mutable perimeter snapshot (health, open incident
    # counts, last scan) with no creation timestamp or server-side time filter, so full refresh.
    "sources": GitGuardianEndpointConfig(
        name="sources",
        path="/v1/sources",
        required_scope="sources:read",
        incremental_fields=[],
    ),
    # Honeytokens: a small config-and-status table (status / triggered_at / revoked_at mutate),
    # so full refresh.
    "honeytokens": GitGuardianEndpointConfig(
        name="honeytokens",
        path="/v1/honeytokens",
        required_scope="honeytokens:read",
        incremental_fields=[],
    ),
    # Workspace members: small mutable directory (role, last_login), full refresh.
    "members": GitGuardianEndpointConfig(
        name="members",
        path="/v1/members",
        required_scope="members:read",
        incremental_fields=[],
    ),
    # Teams: small mutable directory, full refresh.
    "teams": GitGuardianEndpointConfig(
        name="teams",
        path="/v1/teams",
        required_scope="teams:read",
        incremental_fields=[],
    ),
    # Team memberships: the member <-> team join table, fanned out per team. The row carries
    # `team_id` itself, so it leads the key to keep it unique across the fanned-out teams.
    "team_memberships": GitGuardianEndpointConfig(
        name="team_memberships",
        path="/v1/teams/{parent_id}/team_memberships",
        parent_endpoint="teams",
        primary_keys=["team_id", "id"],
        required_scope="teams:read",
        incremental_fields=[],
    ),
    # Honeytoken events: every trigger of every honeytoken. `triggered_at` is immutable and the
    # endpoint accepts `ordering=triggered_at`, but there is no server-side time filter and
    # `status` mutates on triage, so full refresh.
    "honeytoken_events": GitGuardianEndpointConfig(
        name="honeytoken_events",
        path="/v1/honeytokens_events",
        partition_key="triggered_at",
        ordering="triggered_at",
        required_scope="honeytokens:read",
        incremental_fields=[],
        statuses=("open", "archived", "allowed"),
    ),
    # Incident activity logs: the state-transition and notes history of each secret incident,
    # fanned out per incident. There is no server-side time filter, so full refresh. Off by
    # default because it costs at least one request per incident.
    "secret_incident_activity_logs": GitGuardianEndpointConfig(
        name="secret_incident_activity_logs",
        path="/v1/incidents/secrets/{parent_id}/activity-logs",
        parent_endpoint="secret_incidents",
        partition_key="created_at",
        ordering="created_at",
        primary_keys=["incident_id", "id"],
        required_scope="incidents:read",
        should_sync_default=False,
        incremental_fields=[],
    ),
    # Incident notes: analyst comments left on each secret incident, fanned out per incident.
    # Notes can be edited (`updated_at`) and there is no server-side time filter, so full
    # refresh. Off by default because it costs at least one request per incident.
    "secret_incident_notes": GitGuardianEndpointConfig(
        name="secret_incident_notes",
        path="/v1/incidents/secrets/{parent_id}/notes",
        parent_endpoint="secret_incidents",
        partition_key="created_at",
        ordering="created_at",
        primary_keys=["incident_id", "id"],
        required_scope="incidents:read",
        should_sync_default=False,
        incremental_fields=[],
    ),
    # Incident leaks: the public places (GitHub repos, issues, gists) where each incident's secret
    # surfaced. The endpoint is unpaginated and its rows carry no id or incident id, so the
    # incident id is stamped on and the leak URL completes the key. Off by default because it
    # costs one request per incident.
    "secret_incident_leaks": GitGuardianEndpointConfig(
        name="secret_incident_leaks",
        path="/v1/incidents/secrets/{parent_id}/leaks",
        parent_endpoint="secret_incidents",
        parent_id_field="incident_id",
        page_size=None,
        primary_keys=["incident_id", "url"],
        required_scope="incidents:read",
        should_sync_default=False,
        incremental_fields=[],
    ),
    # Team sources: the source <-> team join table, fanned out per team. Rows are full source
    # objects with no team id, so the team id is stamped on to keep the key unique across teams.
    # Also needs `sources:read`, so the probe checks `/v1/sources` too.
    "team_sources": GitGuardianEndpointConfig(
        name="team_sources",
        path="/v1/teams/{parent_id}/sources",
        parent_endpoint="teams",
        parent_id_field="team_id",
        also_requires=("sources",),
        primary_keys=["team_id", "id"],
        required_scope="teams:read",
        incremental_fields=[],
    ),
    # Public perimeter developers: developers GitGuardian links to the organization for public
    # monitoring. The endpoint takes no paging params and has no time filter, so full refresh.
    # Off by default because it needs the Public Monitoring product.
    "public_developers": GitGuardianEndpointConfig(
        name="public_developers",
        path="/v1/public-perimeter/developers",
        page_size=None,
        required_scope="public-perimeter:read",
        should_sync_default=False,
        incremental_fields=[],
    ),
    # Secret detectors: lookup for the detector stamped on incidents and occurrences. Keyed by
    # `name` (the API has no numeric id); open/resolved counts mutate, so full refresh.
    "secret_detectors": GitGuardianEndpointConfig(
        name="secret_detectors",
        path="/v1/secret_detectors",
        ordering="name",
        primary_keys=["name"],
        required_scope="incidents:read",
        incremental_fields=[],
    ),
    # Custom tags: small key/value lookup resolving the custom tag ids applied to incidents. No
    # timestamps or time filter, so full refresh.
    "custom_tags": GitGuardianEndpointConfig(
        name="custom_tags",
        path="/v1/custom_tags",
        required_scope="custom_tags:read",
        incremental_fields=[],
    ),
    # Audit logs: immutable, org-wide trail of workspace events. The endpoint accepts a
    # server-side `date_after` filter but no `ordering` param and documents no default order, so
    # the response is declared desc. Off by default because the `audit_logs:read` scope is not
    # granted to every token.
    "audit_logs": GitGuardianEndpointConfig(
        name="audit_logs",
        path="/v1/audit_logs",
        default_incremental_field="date",
        partition_key="date",
        sort_mode="desc",
        required_scope="audit_logs:read",
        resumable=True,
        should_sync_default=False,
        incremental_fields=_DATE_INCREMENTAL_FIELD,
    ),
    # Public secret incidents: secrets leaked on public GitHub, a perimeter separate from the
    # internal incidents. Same `date_after` + `ordering=date` semantics and mutable triage fields
    # as `secret_incidents`, hence the same lookback. Off by default because it needs the Public
    # Monitoring product.
    "public_secret_incidents": GitGuardianEndpointConfig(
        name="public_secret_incidents",
        path="/v1/public-incidents/secrets",
        default_incremental_field="date",
        partition_key="date",
        ordering="date",
        required_scope="incidents:read",
        incremental_lookback=timedelta(days=7),
        resumable=True,
        should_sync_default=False,
        excluded_fields=frozenset({"share_url"}),
        incremental_fields=_DATE_INCREMENTAL_FIELD,
    ),
}

ENDPOINTS = tuple(GITGUARDIAN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GITGUARDIAN_ENDPOINTS.items()
}
