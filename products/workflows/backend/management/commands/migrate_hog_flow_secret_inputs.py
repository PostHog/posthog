import uuid
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.core.paginator import Paginator
from django.db import transaction

import structlog

from products.workflows.backend.api.hog_flow import (
    TemplateCache,
    merge_secret_maps,
    plaintext_secret_map,
    strip_secrets_from_content,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Move legacy plaintext secret inputs (rows written before encryption shipped) out of "
        "actions/trigger/draft into the encrypted columns. Dry-run by default; pass --live to write."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, help="Only process flows for this team")
        parser.add_argument("--hog-flow-id", type=str, help="Only process this flow")
        parser.add_argument("--live", action="store_true", help="Actually write changes (default is dry-run)")
        parser.add_argument("--page-size", type=int, default=500)

    def handle(self, *args: Any, **options: Any) -> None:
        live = options["live"]
        queryset = HogFlow.objects.all()
        if options.get("hog_flow_id"):
            queryset = queryset.filter(id=options["hog_flow_id"])
        elif options.get("team_id"):
            queryset = queryset.filter(team_id=options["team_id"])

        migrated = 0
        scanned = 0
        errors = 0
        # Templates are a shared global registry, so one cache serves the whole run.
        template_cache: TemplateCache = {}
        paginator = Paginator(queryset.order_by("id"), options["page_size"])
        for page_num in paginator.page_range:
            for flow in paginator.page(page_num).object_list:
                scanned += 1
                try:
                    live_plaintext = plaintext_secret_map(flow.actions, template_cache)
                    draft_plaintext = plaintext_secret_map((flow.draft or {}).get("actions"), template_cache)
                    if not live_plaintext and not draft_plaintext:
                        continue

                    keys_desc = {
                        action_id: sorted(values) for action_id, values in (live_plaintext | draft_plaintext).items()
                    }
                    self.stdout.write(
                        f"{'MIGRATE' if live else 'DRY-RUN'} flow={flow.id} team={flow.team_id} "
                        f"status={flow.status} secret_keys={keys_desc}"
                    )
                    if not live:
                        migrated += 1
                        continue

                    if self._migrate_locked(flow.id, template_cache):
                        migrated += 1
                except Exception as e:
                    errors += 1
                    logger.error(
                        "Error migrating hog flow secret inputs",
                        hog_flow_id=str(flow.id),
                        team_id=flow.team_id,
                        error=str(e),
                        exc_info=True,
                    )
                    self.stdout.write(self.style.ERROR(f"ERROR flow={flow.id}: {e}"))

        summary = f"Scanned {scanned} flows; {'migrated' if live else 'would migrate'} {migrated}; errors {errors}"
        self.stdout.write(self.style.SUCCESS(summary))

    def _migrate_locked(self, flow_id: uuid.UUID, template_cache: TemplateCache) -> bool:
        # API saves to these columns all lock the row (select_for_update) - do the same, and rebuild
        # the secret maps from the locked row, so a concurrent edit or rotation in the window between
        # the scan and this write is never overwritten with stale content.
        with transaction.atomic():
            flow = HogFlow.objects.select_for_update().get(id=flow_id)
            live_plaintext = plaintext_secret_map(flow.actions, template_cache)
            draft_plaintext = plaintext_secret_map((flow.draft or {}).get("actions"), template_cache)
            if not live_plaintext and not draft_plaintext:
                return False

            # Only rewrite the secret columns, not updated_at: this is a backend storage migration, not a
            # user-facing edit. Bumping the stamp would fail the optimistic-concurrency check on any open
            # editor's next save and re-sort untouched flows to the top of the updated_at-ordered list.
            update_fields: list[str] = []
            if live_plaintext:
                content = {"actions": flow.actions, "trigger": flow.trigger}
                stripped = strip_secrets_from_content(content, template_cache)
                flow.actions = content["actions"]
                flow.trigger = content["trigger"]
                # Values already moved to encrypted storage win over stale plaintext copies.
                flow.encrypted_inputs = merge_secret_maps(stripped, flow.encrypted_inputs)
                update_fields += ["actions", "trigger", "encrypted_inputs"]
            if draft_plaintext:
                draft = dict(flow.draft or {})
                stripped = strip_secrets_from_content(draft, template_cache)
                flow.draft = draft
                flow.draft_encrypted_inputs = merge_secret_maps(stripped, flow.draft_encrypted_inputs)
                update_fields += ["draft", "draft_encrypted_inputs"]
            flow.save(update_fields=update_fields)
        return True
