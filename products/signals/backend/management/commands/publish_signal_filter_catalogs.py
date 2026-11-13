from django.core.management.base import BaseCommand

from products.signals.backend.filter_catalog import SignalFilterSourceDefinition
from products.signals.backend.filter_catalog_seeds import CATALOG_SEEDS


class Command(BaseCommand):
    help = "Publish the checked-in signal filter catalogs. Safe to rerun: an unchanged catalog creates no version."

    def handle(self, *args: object, **options: object) -> None:
        for seed in CATALOG_SEEDS:
            publication = SignalFilterSourceDefinition.publish(
                source_product=seed.source_product,
                source_type=seed.source_type,
                adapter_kind=seed.adapter_kind,
                initial_rollout_state=seed.initial_rollout_state,
                bundle=seed.bundle,
            )
            outcome = "published" if publication.version_created else "unchanged"
            self.stdout.write(f"{seed.source_product}/{seed.source_type}: {outcome} at version {publication.version}")
