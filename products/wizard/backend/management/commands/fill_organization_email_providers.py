"""Set the `email_providers` organization property for organizations scanned before the property existed.

A one-off, safe to run again: each send carries the full list.

Usage:
    python manage.py fill_organization_email_providers
    python manage.py fill_organization_email_providers --apply --limit 5
    python manage.py fill_organization_email_providers --apply
"""

from argparse import ArgumentParser
from collections import Counter
from collections.abc import Iterator
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import posthoganalytics

from posthog.ph_client import self_hosted_capture_reaches_posthog
from posthog.schema_enums import ProductKey

from products.wizard.backend.logic.scans import organization_email_providers, send_organization_email_providers
from products.wizard.backend.models import WizardDetectedTool
from products.wizard.backend.tool_catalog.catalog import kinds_alternative_to

BATCH_SIZE = 100


class Command(BaseCommand):
    help = "Set the email_providers organization property from the email providers that wizard scans already found."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--apply", action="store_true", help="Send the property. Without it, only counts.")
        parser.add_argument("--limit", type=int, help="Stop after this many organizations.")
        parser.add_argument("--organization-id", type=UUID, help="Only this organization.")

    def handle(self, *args: Any, **options: Any) -> None:
        limit: int | None = options["limit"]
        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1")

        errors: list[Exception] = []
        client = self._client(errors) if options["apply"] else None
        organizations = 0
        organizations_per_provider: Counter[str] = Counter()
        try:
            for batch in self._batches(limit, options["organization_id"]):
                for organization_id in batch:
                    providers = organization_email_providers(organization_id)
                    if not providers:
                        # The replica can still list rows that the writer has deleted.
                        continue
                    if client and send_organization_email_providers(organization_id, providers, client=client) is None:
                        raise CommandError("An event was not queued. Run again to resend everything.")
                    organizations += 1
                    organizations_per_provider.update(providers)
                if client:
                    client.flush(timeout_seconds=None)
                    if errors:
                        raise CommandError(
                            f"Sending failed after at most {organizations} organizations: {errors[0]}. "
                            "Run again to resend everything."
                        )
                self.stdout.write(f"{'Sent' if client else 'Counted'} {organizations} organizations so far")
        finally:
            if client:
                client.shutdown()

        for provider, count in sorted(organizations_per_provider.items()):
            self.stdout.write(f"{provider}: {count}")
        self.stdout.write(
            f"{'Sent' if client else 'Dry run, nothing sent. Would send'} email_providers "
            f"for {organizations} organizations"
        )

    @staticmethod
    def _client(errors: list[Exception]) -> posthoganalytics.Client:
        if posthoganalytics.disabled or self_hosted_capture_reaches_posthog():
            raise CommandError("Analytics capture is off in this process, or this is a self-hosted instance.")
        # The shared client cannot report failed sends. Its key and host are reused, so the events land in the
        # project that scans send to.
        return posthoganalytics.Client(
            posthoganalytics.api_key,
            host=posthoganalytics.host,
            super_properties=posthoganalytics.super_properties,
            on_error=lambda error, _batch: errors.append(error),
        )

    @staticmethod
    def _batches(limit: int | None, only_organization_id: UUID | None) -> Iterator[list[str]]:
        rows = (
            WizardDetectedTool.objects.unscoped()
            .using("replica" if "replica" in settings.DATABASES else "default")
            .filter(kind__in=kinds_alternative_to(ProductKey.WORKFLOWS))
        )
        if only_organization_id:
            rows = rows.filter(team__organization_id=only_organization_id)
        remaining = limit
        last: UUID | None = None
        while remaining is None or remaining > 0:
            page = rows.filter(team__organization_id__gt=last) if last else rows
            size = BATCH_SIZE if remaining is None else min(BATCH_SIZE, remaining)
            ids = list(
                page.order_by("team__organization_id").values_list("team__organization_id", flat=True).distinct()[:size]
            )
            if not ids:
                return
            yield [str(organization_id) for organization_id in ids]
            last = ids[-1]
            if remaining is not None:
                remaining -= len(ids)
