from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from posthog.plugins.plugin_server_api import reload_hog_flows_on_workers

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

# The email step's sender picker persisted this fallback into from.email on every sender pick
# between Aug 2025 (#35984) and June 2026 (#60438). The value was inert until #83059 made
# from.email load-bearing; #84891 made the send path tolerate it. This removes the stored value
# so the tolerate-and-warn fallback stops firing and the field again means "the author set this".
PLACEHOLDER_SENDER = "default@example.com"


def _strip_placeholder(actions: list | None) -> int:
    stripped = 0
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        email_input = ((action.get("config") or {}).get("inputs") or {}).get("email")
        value = email_input.get("value") if isinstance(email_input, dict) else None
        from_value = value.get("from") if isinstance(value, dict) else None
        if isinstance(from_value, dict) and from_value.get("email") == PLACEHOLDER_SENDER:
            del from_value["email"]
            stripped += 1
    return stripped


class Command(BaseCommand):
    help = (
        f"Remove the legacy '{PLACEHOLDER_SENDER}' sender override the pre-June-2026 email step "
        "picker stored on workflow email actions (live actions and the draft blob). Only that exact "
        "literal is removed; addresses an author typed are never touched. Idempotent. Default "
        "dry-run; pass --live-run to apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Limit to a specific team ID")
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")

    def handle(self, *args, **options):
        live_run = options.get("live_run", False)
        team_id = options.get("team_id")
        mode = "LIVE RUN" if live_run else "DRY RUN"
        self.stdout.write(f"Starting strip_placeholder_sender_overrides ({mode})")

        flows = HogFlow.objects.filter(
            Q(actions__icontains=PLACEHOLDER_SENDER) | Q(draft__icontains=PLACEHOLDER_SENDER)
        )
        if team_id:
            flows = flows.filter(team_id=team_id)
            self.stdout.write(f"Filtering to team_id={team_id}")

        flows_changed = 0
        overrides_stripped = 0
        for flow in flows.iterator():
            live_stripped = _strip_placeholder(flow.actions)
            draft_actions = (flow.draft or {}).get("actions") if isinstance(flow.draft, dict) else None
            draft_stripped = _strip_placeholder(draft_actions)
            if not live_stripped and not draft_stripped:
                continue

            if not live_run:
                self.stdout.write(
                    f"  Would strip {live_stripped} live / {draft_stripped} draft "
                    f"override(s) on flow id={flow.id} team_id={flow.team_id} status={flow.status}"
                )
                flows_changed += 1
                overrides_stripped += live_stripped + draft_stripped
                continue

            # Re-read the row under a lock and strip that value, not the one the scan saw. A
            # customer saving the workflow between the scan and this write would otherwise have
            # their edit overwritten by the stale blob this command is holding - the same lost
            # write rewrite_email_asset_url and the API save paths guard against.
            with transaction.atomic():
                locked = HogFlow.objects.select_for_update().get(pk=flow.pk)
                live_stripped = _strip_placeholder(locked.actions)
                locked_draft_actions = (locked.draft or {}).get("actions") if isinstance(locked.draft, dict) else None
                draft_stripped = _strip_placeholder(locked_draft_actions)
                if not live_stripped and not draft_stripped:
                    continue

                update_fields: dict = {}
                if live_stripped:
                    update_fields["actions"] = locked.actions
                if draft_stripped:
                    update_fields["draft"] = locked.draft
                # .update() avoids bumping updated_at / firing save signals for a backfill; workers
                # cache the live flow config, so a live-actions change needs an explicit reload.
                HogFlow.objects.filter(pk=locked.pk).update(**update_fields)

            self.stdout.write(
                f"  Stripping {live_stripped} live / {draft_stripped} draft "
                f"override(s) on flow id={flow.id} team_id={flow.team_id} status={flow.status}"
            )
            flows_changed += 1
            overrides_stripped += live_stripped + draft_stripped
            if live_stripped:
                reload_hog_flows_on_workers(team_id=flow.team_id, hog_flow_ids=[str(flow.id)])

        verb = "stripped" if live_run else "to strip"
        self.stdout.write(
            self.style.SUCCESS(
                f"Completed ({mode}): {overrides_stripped} override(s) {verb} across {flows_changed} flow(s)"
            )
        )
        if not live_run and flows_changed > 0:
            self.stdout.write(self.style.NOTICE("Run with --live-run to apply changes"))
