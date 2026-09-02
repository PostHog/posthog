import logging
from functools import partial
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from posthog.plugins.plugin_server_api import reload_hog_flows_on_workers

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

logger = logging.getLogger(__name__)

# The email step's sender picker persisted this fallback into from.email on every sender pick
# between Aug 2025 (#35984) and June 2026 (#60438). The value was inert until #83059 made
# from.email load-bearing; #84891 made the send path tolerate it. This removes the stored value
# so the tolerate-and-warn fallback stops firing and the field again means "the author set this".
PLACEHOLDER_SENDER = "default@example.com"


def _strip_placeholder(actions: list[Any] | None) -> int:
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

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", default=None, type=int, help="Limit to a specific team ID")
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")

    def handle(self, *args: Any, **options: Any) -> None:
        live_run: bool = options.get("live_run", False)
        team_id: int | None = options.get("team_id")
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
        flows_failed = 0
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
            # write rewrite_email_asset_url and the API save paths guard against. One failed row
            # (a lock timeout, a Redis blip on the reload publish) must not abandon the rest of
            # the sweep: each row commits on its own and the command is idempotent, so a rerun
            # recovers the failed ones.
            try:
                with transaction.atomic():
                    locked = HogFlow.objects.select_for_update().get(pk=flow.pk)
                    live_stripped = _strip_placeholder(locked.actions)
                    locked_draft_actions = (
                        (locked.draft or {}).get("actions") if isinstance(locked.draft, dict) else None
                    )
                    draft_stripped = _strip_placeholder(locked_draft_actions)
                    if not live_stripped and not draft_stripped:
                        continue

                    update_fields: list[str] = []
                    if live_stripped:
                        # updated_at is auto_now, so listing it is enough. Bumping it lets the
                        # editor's stale-write fence reject a tab opened before the cleanup, which
                        # still holds the placeholder and would otherwise save it straight back.
                        update_fields += ["actions", "updated_at"]
                    if draft_stripped:
                        locked.draft_updated_at = timezone.now()
                        update_fields += ["draft", "draft_updated_at"]
                    locked.save(update_fields=update_fields)

                    # The post_save receiver publishes the worker reload from inside this
                    # transaction, so a worker can re-read the row before the UPDATE commits and
                    # cache the old blob for another refresh window. Publishing again on commit is
                    # what workers actually act on; the duplicate is harmless. Draft-only strips
                    # publish nothing, matching the receiver that skips them.
                    if live_stripped:
                        transaction.on_commit(
                            partial(
                                reload_hog_flows_on_workers,
                                team_id=locked.team_id,
                                hog_flow_ids=[str(locked.pk)],
                            )
                        )
            except Exception:
                logger.exception("Failed to strip placeholder sender", extra={"hog_flow_id": str(flow.pk)})
                self.stderr.write(f"  FAILED on flow id={flow.id} team_id={flow.team_id}; continuing")
                flows_failed += 1
                continue

            self.stdout.write(
                f"  Stripping {live_stripped} live / {draft_stripped} draft "
                f"override(s) on flow id={flow.id} team_id={flow.team_id} status={flow.status}"
            )
            flows_changed += 1
            overrides_stripped += live_stripped + draft_stripped

        verb = "stripped" if live_run else "to strip"
        self.stdout.write(
            self.style.SUCCESS(
                f"Completed ({mode}): {overrides_stripped} override(s) {verb} across {flows_changed} flow(s)"
            )
        )
        if flows_failed:
            self.stderr.write(self.style.ERROR(f"{flows_failed} flow(s) failed; rerun to retry them"))
        if not live_run and flows_changed > 0:
            self.stdout.write(self.style.NOTICE("Run with --live-run to apply changes"))
