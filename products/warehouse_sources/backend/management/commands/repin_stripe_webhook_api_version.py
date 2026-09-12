from typing import Any, cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

import structlog

from posthog.dataclasses import frozen

from products.cdp.backend.facade.models import HogFunction
from products.data_warehouse.backend.facade.api import get_webhook_url, store_webhook_extra_inputs
from products.warehouse_sources.backend.facade.source_management import SourceRegistry
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stripe import StripeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source import StripeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import WebhookRepin
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)


@frozen
class _RepinCandidate:
    source_model: ExternalDataSource
    hog_function: HogFunction
    config: StripeSourceConfig
    webhook_url: str
    current_api_version: str | None
    target_api_version: str


class Command(BaseCommand):
    help = (
        "Pin the Stripe API version on webhook endpoints that were created without one. An unpinned "
        "endpoint delivers at the Stripe account's default version, so its payloads can carry a "
        "different shape from the version the source reads, and the fields that moved between "
        "versions land as NULL. Stripe accepts api_version on create only, so each endpoint is "
        "replaced: the command creates a pinned endpoint on the same URL, stores its signing secret, "
        "then deletes the old endpoint. Both endpoints receive every event while both exist, and one "
        "copy always verifies against the stored secret, so no event is lost."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually replace the endpoints. Without this flag the command only reports (dry-run).",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Only consider sources belonging to this team",
        )
        parser.add_argument(
            "--source-id",
            action="append",
            default=None,
            help="Target these source ids explicitly. Repeatable.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help=(
                "Only scan the first N Stripe sources. Each one costs a Stripe API call even in a "
                "dry run, so use this for a first batch."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        live_run = options["live_run"]
        source = cast(StripeSource, SourceRegistry.get_source(ExternalDataSourceType.STRIPE))

        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be at least 1.")

        candidates = self._find_candidates(
            source, team_id=options["team_id"], source_ids=options["source_id"], limit=options["limit"]
        )

        if not candidates:
            self.stdout.write(self.style.WARNING("No Stripe webhook endpoint needs repinning."))
            return

        self.stdout.write(f"Found {len(candidates)} Stripe webhook endpoint(s) on the wrong API version:\n")
        for candidate in candidates:
            self.stdout.write(
                f"  source={candidate.source_model.id} team={candidate.source_model.team_id} "
                f"endpoint_version={candidate.current_api_version or 'unpinned'} "
                f"target={candidate.target_api_version}"
            )

        if not live_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run: {len(candidates)} endpoint(s) would be replaced. Pass --live-run to execute."
                )
            )
            return

        self._replace(source, candidates)

    def _find_candidates(
        self, source: StripeSource, *, team_id: int | None, source_ids: list[str] | None, limit: int | None
    ) -> list[_RepinCandidate]:
        sources = ExternalDataSource.objects.filter(
            source_type=ExternalDataSourceType.STRIPE,
            deleted=False,
        ).order_by("created_at")

        if team_id is not None:
            sources = sources.filter(team_id=team_id)
        if source_ids:
            sources = sources.filter(id__in=source_ids)
        if limit is not None:
            sources = sources[:limit]

        candidates: list[_RepinCandidate] = []

        for source_model in sources:
            hog_function = HogFunction.objects.filter(
                team_id=source_model.team_id,
                type="warehouse_source_webhook",
                inputs__source_id__value=str(source_model.id),
                deleted=False,
            ).first()
            if hog_function is None or not source_model.job_inputs:
                continue

            webhook_url = get_webhook_url(str(hog_function.id))
            target_api_version = source.resolve_api_version(source_model.api_version)

            try:
                config = source.parse_config(source_model.job_inputs)
                info = source.get_external_webhook_info(config, webhook_url, source_model.team_id)
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f"Skipped source={source_model.id}: could not read the endpoint ({e})")
                )
                continue

            if not info.exists or info.api_version == target_api_version:
                continue

            # The Stripe app is structurally denied `webhook_write`, so the replacement create can
            # only 403 for an app-connected source. Report it as needing a manual fix in Stripe
            # rather than queueing a candidate that fails on every run.
            if config.auth_method.selection == "oauth":
                self.stdout.write(
                    self.style.WARNING(
                        f"Manual fix needed for source={source_model.id} team={source_model.team_id}: "
                        f"an app-connected source cannot create a webhook endpoint. Recreate it in Stripe "
                        f"on {info.api_version or 'no version'} → {target_api_version}."
                    )
                )
                continue

            candidates.append(
                _RepinCandidate(
                    source_model=source_model,
                    hog_function=hog_function,
                    config=config,
                    webhook_url=webhook_url,
                    current_api_version=info.api_version,
                    target_api_version=target_api_version,
                )
            )

        return candidates

    def _replace(self, source: StripeSource, candidates: list[_RepinCandidate]) -> None:
        replaced = 0
        failed = 0
        orphaned = 0

        for candidate in candidates:
            source_model = candidate.source_model
            repin = source.create_pinned_webhook_replacement(
                candidate.config,
                candidate.webhook_url,
                source_model.team_id,
                api_version=source_model.api_version,
            )

            if repin.status != "replaced" or not repin.signing_secret or not repin.replaced_endpoint_id:
                failed += 1
                reason = repin.error or f"the endpoint is now {repin.status}"
                self.stdout.write(self.style.ERROR(f"Failed source={source_model.id}: {reason}"))
                self._report_stray_endpoint(source_model, repin)
                continue

            try:
                # Store the secret before the delete. Until this write lands only the old endpoint's
                # deliveries verify, and after it lands only the new endpoint's do, so every event
                # has one copy that verifies as long as both endpoints exist.
                store_webhook_extra_inputs(
                    str(candidate.hog_function.id),
                    source_model.team_id,
                    {"signing_secret": repin.signing_secret},
                )
            except Exception as e:
                # The replacement is live in Stripe and its secret is stored nowhere, so name it
                # here rather than letting the traceback end the run with the id only in Stripe.
                failed += 1
                self.stdout.write(self.style.ERROR(f"Failed source={source_model.id}: {e}"))
                self._report_stray_endpoint(source_model, repin)
                continue

            deletion = source.delete_webhook_endpoint(
                candidate.config, repin.replaced_endpoint_id, source_model.team_id
            )
            if not deletion.success:
                orphaned += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Replaced source={source_model.id} but could not delete the old endpoint "
                        f"{repin.replaced_endpoint_id}: {deletion.error}. Delete it in Stripe, because "
                        f"its deliveries now fail the signature check."
                    )
                )

            replaced += 1
            logger.info(
                "Repinned Stripe webhook endpoint",
                source_id=str(source_model.id),
                team_id=source_model.team_id,
                previous_api_version=repin.previous_api_version,
                api_version=candidate.target_api_version,
            )

        self.stdout.write(
            self.style.SUCCESS(f"\nDone. Replaced: {replaced}, Failed: {failed}, Old endpoint left behind: {orphaned}")
        )

    def _report_stray_endpoint(self, source_model: ExternalDataSource, repin: WebhookRepin) -> None:
        if not repin.created_endpoint_id:
            return
        self.stdout.write(
            self.style.WARNING(
                f"  Stripe endpoint {repin.created_endpoint_id} exists for source={source_model.id} "
                f"and nothing holds its signing secret. Delete it in Stripe."
            )
        )
