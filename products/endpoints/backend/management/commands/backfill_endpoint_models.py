from argparse import ArgumentParser

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from products.data_modeling.backend.facade.api import get_node_ids_for_saved_queries
from products.endpoints.backend.logic.materialization import EndpointModelService
from products.endpoints.backend.models import EndpointVersion


class Command(BaseCommand):
    help = "Create models and lineage for existing endpoint versions."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--limit", type=int, default=1000)
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        team_id = int(str(options["team_id"]))
        batch_size = int(str(options["batch_size"]))
        limit = int(str(options["limit"]))
        offset = int(str(options["offset"]))
        if offset < 0:
            raise CommandError("Offset must be nonnegative.")
        if batch_size < 1 or limit < 1:
            raise CommandError("Batch size and limit must be positive.")
        versions = (
            EndpointVersion.objects.filter(endpoint__team_id=team_id, endpoint__deleted=False)
            .select_related("endpoint__team", "created_by", "saved_query")
            .order_by("endpoint_id", "version")[offset : offset + limit]
        )
        processed = 0
        for version in versions.iterator(chunk_size=batch_size):
            if options["dry_run"]:
                self.stdout.write(f"Would ensure model for {version.endpoint.name} v{version.version}")
            else:
                previous = (
                    EndpointVersion.objects.filter(endpoint_id=version.endpoint_id, version__lt=version.version)
                    .order_by("-version")
                    .first()
                )
                with transaction.atomic():
                    EndpointModelService(version.endpoint.team, version.created_by).ensure_model(
                        version.endpoint, version, previous_version=previous
                    )
                node_ids = get_node_ids_for_saved_queries(
                    team_id, [str(version.saved_query_id)] if version.saved_query_id else []
                )
                state = "ready" if node_ids else "lineage unavailable"
                self.stdout.write(f"{version.endpoint.name} v{version.version}: {state}")
            processed += 1
        self.stdout.write(f"Processed {processed} endpoint versions. Next offset: {offset + processed}.")
