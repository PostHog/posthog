from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
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
    page_size: int = 100  # GitGuardian caps per_page at 100
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
}

ENDPOINTS = tuple(GITGUARDIAN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GITGUARDIAN_ENDPOINTS.items()
}
