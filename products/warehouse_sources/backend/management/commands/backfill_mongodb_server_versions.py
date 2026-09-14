"""Record the MongoDB version and wire version each MongoDB source's cluster reports.

The schema-discovery pass records this for every source on its own schedule, so this command is
for answering the question now instead of waiting for that pass to come round. The wire version
decides whether a source survives a pymongo wire-version floor change, and no other column holds
it, so an upgrade that raises the floor is otherwise unmeasurable until customer syncs start
failing.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

import structlog

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

# pymongo 4.14 raised its floor from wire version 7 (MongoDB 4.0) to 8 (MongoDB 4.2), so a source
# below this reports a cluster that release would refuse to talk to.
PYMONGO_MIN_WIRE_VERSION = 8


class Command(BaseCommand):
    help = (
        "Probe every MongoDB source for the server version its cluster reports and store it on the "
        "source's connection_metadata. Reports a version breakdown and how many clusters sit below "
        "the current pymongo wire-version floor. Previews by default; pass --live-run to persist."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Only probe sources belonging to this team.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Only probe the first N sources, for a cautious first batch.",
        )
        parser.add_argument(
            "--refresh",
            action="store_true",
            help="Re-probe sources that already have a recorded server version.",
        )
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Persist the probed versions. Without this the command only reports what it found.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        sources = self._sources(team_id=options["team_id"], limit=options["limit"], refresh=options["refresh"])
        live_run = options["live_run"]
        source_impl = SourceRegistry.get_source(ExternalDataSourceType.MONGODB)

        versions: dict[str, int] = {}
        below_floor = 0
        probed = 0
        failed = 0

        for source in sources:
            metadata = self._probe(source_impl, source)
            if metadata is None:
                failed += 1
                continue

            probed += 1
            version = str(metadata.get("server_version") or "unknown")
            versions[version] = versions.get(version, 0) + 1
            wire_version = metadata.get("wire_version")
            if isinstance(wire_version, int) and wire_version < PYMONGO_MIN_WIRE_VERSION:
                below_floor += 1
                self.stdout.write(
                    f"source {source.id} (team {source.team_id}): MongoDB {version}, "
                    f"wire version {wire_version} is below the pymongo floor of {PYMONGO_MIN_WIRE_VERSION}"
                )

            if live_run:
                # Only connection_metadata is written, so `updated_at` keeps the time of the last
                # real change to the source and a backfill does not read as a customer edit.
                source.connection_metadata = {**(source.connection_metadata or {}), **metadata}
                source.save(update_fields=["connection_metadata"])

        self.stdout.write(f"probed {probed}, failed {failed}, below pymongo floor {below_floor}")
        for version, count in sorted(versions.items()):
            self.stdout.write(f"  MongoDB {version}: {count}")
        if not live_run:
            self.stdout.write("preview only, nothing written. Re-run with --live-run to persist.")

    def _sources(self, *, team_id: int | None, limit: int | None, refresh: bool) -> list[ExternalDataSource]:
        sources = ExternalDataSource.objects.filter(
            source_type=ExternalDataSourceType.MONGODB,
            deleted=False,
        ).order_by("created_at")

        if team_id is not None:
            sources = sources.filter(team_id=team_id)
        if not refresh:
            sources = sources.exclude(connection_metadata__server_version__isnull=False)
        if limit is not None:
            sources = sources[:limit]

        # A source with no stored credentials has nothing to connect with, and reaching one costs a
        # full server-selection timeout, so drop those before probing rather than counting them as
        # failures.
        return [source for source in sources if source.job_inputs]

    def _probe(self, source_impl: Any, source: ExternalDataSource) -> dict[str, Any] | None:
        # An unreachable or misconfigured cluster is the common case here, not an exception worth
        # stopping for: this command's whole purpose is to survey a population that includes broken
        # sources, so a failure is logged and the survey continues.
        try:
            config = source_impl.parse_config(source.job_inputs)
            metadata = source_impl.get_server_metadata(config, source.team_id)
        except Exception as error:
            logger.warning(
                "Could not probe MongoDB source",
                source_id=str(source.id),
                team_id=source.team_id,
                error=str(error),
            )
            return None

        return metadata if isinstance(metadata, dict) else None
