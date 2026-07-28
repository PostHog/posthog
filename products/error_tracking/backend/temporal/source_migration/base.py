"""Source adapter contract for error tracking migrations.

The workflow and activities are source-agnostic: everything a source needs to say —
which warehouse schemas it reads, how to page and transform its rows into `$exception`
events, how its statuses map onto issue statuses — lives behind this protocol. Adding a
source means writing one adapter module and registering it in `get_adapter`.
"""

import dataclasses
from typing import Any, Protocol

from posthog.hogql import ast

from products.error_tracking.backend.models import ErrorTrackingIssue


@dataclasses.dataclass
class TransformContext:
    config: dict[str, Any]
    import_job_id: str
    # Issue ids that already got a first-seen anchor event this run; adapters mutate it.
    anchored_issue_ids: set[str]


class MigrationSourceAdapter(Protocol):
    # ErrorTrackingMigration.SourceType value, and the doubled fingerprint namespace.
    source_type: str
    # ExternalDataSource.source_type of the warehouse source this migration reads from.
    external_source_type: str
    # Role -> warehouse schema name. Every schema must be enabled and initially synced
    # before the import runs; tables are resolved per role and passed to the queries.
    schema_roles: dict[str, str]

    def validate_config(self, config: dict[str, Any]) -> str | None:
        """Return a user-facing error when the migration config is unusable, else None."""
        ...

    def fingerprint_prefix(self, config: dict[str, Any]) -> str:
        """Prefix of every fingerprint this migration creates; used to count settled issues."""
        ...

    def issue_fingerprint(self, config: dict[str, Any], issue_key: str) -> str: ...

    def build_events_page_query(
        self, tables: dict[str, str], config: dict[str, Any], cursor: dict[str, Any] | None, page_size: int
    ) -> tuple[str, dict[str, ast.Expr]]: ...

    def build_events_count_query(
        self, tables: dict[str, str], config: dict[str, Any]
    ) -> tuple[str, dict[str, ast.Expr]]:
        """Must select (event_count, issue_count) as a single row."""
        ...

    def build_issue_status_page_query(
        self, tables: dict[str, str], cursor: str | None, page_size: int
    ) -> tuple[str, dict[str, ast.Expr]]:
        """Must select (issue_key, raw_status) rows ordered by issue_key."""
        ...

    def events_for_row(self, row: dict[str, Any], ctx: TransformContext) -> list[dict[str, Any]]:
        """Capture-ready event dicts for one warehouse row; [] skips it (e.g. scope filters)."""
        ...

    def event_cursor(self, row: dict[str, Any]) -> dict[str, Any]:
        """Keyset cursor for resuming after this row."""
        ...

    def map_status(self, raw_status: str | None) -> ErrorTrackingIssue.Status | None:
        """Target issue status for a source status; None leaves the issue active."""
        ...


def get_adapter(source_type: str) -> MigrationSourceAdapter:
    from products.error_tracking.backend.temporal.source_migration.sentry import (  # noqa: PLC0415 — adapters import this module; deferring breaks the cycle
        SentryMigrationAdapter,
    )

    adapters: dict[str, MigrationSourceAdapter] = {
        SentryMigrationAdapter.source_type: SentryMigrationAdapter(),
    }
    adapter = adapters.get(source_type)
    if adapter is None:
        raise ValueError(f"No migration adapter registered for source type {source_type!r}")
    return adapter
