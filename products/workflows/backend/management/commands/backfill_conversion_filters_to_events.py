from django.core.management.base import BaseCommand

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


class Command(BaseCommand):
    help = (
        "Relocate event-based conversion goals stored in the wrong slot. Before the conversion.events "
        "slot existed, an event-based goal could be saved as an object in conversion.filters "
        "(e.g. {'events': [...], 'source': 'events'}). conversion.filters is meant to be an array of "
        "property filters, so the object crashes the property-conversion picker and is invisible to "
        "the subscription matcher (which reads conversion.events). This moves it to "
        "conversion.events = [{filters: <object>}] and clears the property slot. Behaviour-neutral "
        "(no bytecode compiled here; it recompiles on the next save) and idempotent. Default dry-run; "
        "pass --live-run to apply. The serializer guard prevents new rows in this shape, so this only "
        "needs to run once per environment."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Limit to a specific team ID")
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")

    def handle(self, *args, **options):
        live_run = options.get("live_run", False)
        team_id = options.get("team_id")
        mode = "LIVE RUN" if live_run else "DRY RUN"
        self.stdout.write(f"Starting backfill_conversion_filters_to_events ({mode})")

        flows = HogFlow.objects.filter(conversion__isnull=False)
        if team_id:
            flows = flows.filter(team_id=team_id)
            self.stdout.write(f"Filtering to team_id={team_id}")

        relocated = 0
        for flow in flows.iterator():
            conversion = flow.conversion or {}
            filters = conversion.get("filters")

            # A valid conversion.filters is a list of property filters (or absent). The only malformed
            # shape we fix is the event object {"events": [...], "source": "events"} that predates the
            # conversion.events slot. Leave any other shape untouched.
            if not isinstance(filters, dict) or not filters.get("events"):
                continue

            new_conversion = dict(conversion)
            new_conversion["events"] = [*(new_conversion.get("events") or []), {"filters": filters}]
            new_conversion["filters"] = []
            new_conversion["bytecode"] = []

            self.stdout.write(
                f"  {'Relocating' if live_run else 'Would relocate'} conversion for flow id={flow.id} "
                f"team_id={flow.team_id} status={flow.status}"
            )
            if live_run:
                # .update() avoids bumping updated_at / firing save signals for a backfill.
                HogFlow.objects.filter(pk=flow.pk).update(conversion=new_conversion)
            relocated += 1

        verb = "relocated" if live_run else "to relocate"
        self.stdout.write(self.style.SUCCESS(f"Completed ({mode}): {relocated} flow(s) {verb}"))
        if not live_run and relocated > 0:
            self.stdout.write(self.style.NOTICE("Run with --live-run to apply changes"))
