from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from asgiref.sync import async_to_sync

from posthog.llm.gateway_client import resolve_ai_gateway_config
from posthog.llm.gateway_usage import fetch_gateway_cost

from products.signals.backend.models import SignalSpend
from products.signals.backend.spend import record_llm_spend


class Command(BaseCommand):
    help = "Recover a missing generation receipt using its verified gateway request ID."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--spend-id", type=UUID, required=True)
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--request-id", required=True)

    def handle(self, *args: object, **options: object) -> None:
        spend = SignalSpend.objects.for_team(int(str(options["team_id"]))).filter(id=str(options["spend_id"])).first()
        source_id, request_id = str(options["source_id"]), str(options["request_id"])
        source = spend.trial_sources.get(source_id) if spend else None
        if spend is None or source is None or source["is_task"] or not source["accounting_failed"]:
            raise CommandError("Select an incomplete generation source belonging to this team.")
        if source.get("request_id") and source["request_id"] != request_id:
            raise CommandError("This source already has a different request ID.")
        gateway = resolve_ai_gateway_config()
        if gateway is None:
            raise CommandError("AI gateway is not configured.")
        cost = async_to_sync(fetch_gateway_cost)(request_id, base_url=gateway.url, api_key=gateway.api_key)
        if cost is None:
            raise CommandError("The gateway receipt is not available. No cost was changed.")
        record_llm_spend(
            request_id,
            token_cost_microusd=cost.cost_microusd,
            team_id=spend.team_id,
            signal_id=str(spend.signal_id),
            stage=source["stage"],
            source_id=source_id,
            trial_grant_id=source.get("trial_grant_id"),
        )
        self.stdout.write(self.style.SUCCESS("Recovered generation cost from the gateway receipt."))
