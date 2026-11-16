"""Warehouse destination checks used by warehouse presentation endpoints.

Each function defers its import, so loading the presentation layer does not load `duckdb` or
the destination writers into the web process.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.models.team.team import Team


def is_destination_type_enabled(team: "Team", destination_type: str) -> bool:
    """Whether this team may create destinations of this type."""
    from products.warehouse_sources.backend.temporal.data_imports.destinations.enablement import (  # noqa: PLC0415
        is_destination_type_enabled as _is_destination_type_enabled,
    )

    return _is_destination_type_enabled(team, destination_type)


def probe_motherduck_destination(
    access_token: str, database: str, schema: str, *, timeout_seconds: float
) -> str | None:
    """Check that the token can create tables in the MotherDuck database and schema.

    Returns None when it can. Otherwise returns why not: `authentication`, `unknown_database`,
    `missing_privilege` or `unreachable`.
    """
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.motherduck import (  # noqa: PLC0415
        probe_write_access,
    )

    return probe_write_access(access_token, database, schema, timeout_seconds=timeout_seconds)


__all__ = ["is_destination_type_enabled", "probe_motherduck_destination"]
