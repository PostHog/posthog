"""Encode the timestamp in error tracking alert deep links that were created before the fix.

A destination stores the input values it was created with, so the template fix in
`sub-templates.ts` only reaches alerts created after it deploys. Alerts already configured keep
interpolating `exception_timestamp` raw, and the `+00:00` offset the backend emits decodes back to
a space, so their links cannot open the exception they name.

Usage:
    python manage.py backfill_error_tracking_alert_link_encoding
    python manage.py backfill_error_tracking_alert_link_encoding --live-run
    python manage.py backfill_error_tracking_alert_link_encoding --live-run --batch-size 500
"""

from __future__ import annotations

import logging
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import TextField
from django.db.models.functions import Cast

import structlog

from posthog.cdp.validation import generate_template_bytecode

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)

DEFAULT_BATCH_SIZE = 1_000

# The exact substring the old template produced. Matching it rather than the whole link keeps a
# destination whose message a customer has since rewritten out of scope unless it still carries
# this interpolation.
UNENCODED_TIMESTAMP = "timestamp={event.properties.exception_timestamp}"
ENCODED_TIMESTAMP = (
    "timestamp={event.properties.exception_timestamp ? encodeURLComponent(event.properties.exception_timestamp) : ''}"
)


def replace_in_input_value(value: Any) -> tuple[Any, bool]:
    """Rewrite every string inside one input value. A link can sit in a bare string (Linear,
    GitHub), in markdown prose (Discord, Microsoft Teams), or nested in a block structure (Slack)."""
    if isinstance(value, str):
        if UNENCODED_TIMESTAMP not in value:
            return value, False
        return value.replace(UNENCODED_TIMESTAMP, ENCODED_TIMESTAMP), True
    if isinstance(value, dict):
        rewritten = {}
        changed = False
        for key, item in value.items():
            rewritten[key], item_changed = replace_in_input_value(item)
            changed = changed or item_changed
        return rewritten, changed
    if isinstance(value, list):
        rewritten_list = []
        changed = False
        for item in value:
            new_item, item_changed = replace_in_input_value(item)
            rewritten_list.append(new_item)
            changed = changed or item_changed
        return rewritten_list, changed
    return value, False


def rewrite_inputs(destination: HogFunction) -> tuple[dict[str, Any] | None, str | None]:
    """Return the destination's inputs with every alert link encoded, or None when it carries none.
    The second element is the compiler error when one input cannot be recompiled."""
    rewritten: dict[str, Any] = {}
    changed = False

    for key, entry in (destination.inputs or {}).items():
        if not isinstance(entry, dict):
            rewritten[key] = entry
            continue
        new_value, entry_changed = replace_in_input_value(entry.get("value"))
        if not entry_changed:
            rewritten[key] = entry
            continue
        input_collector: set[str] = set()
        try:
            bytecode = generate_template_bytecode(new_value, input_collector, function_type=destination.type)
        except Exception as error:
            return None, str(error)
        rewritten[key] = {
            **entry,
            "value": new_value,
            "bytecode": bytecode,
            "input_deps": list(input_collector),
        }
        changed = True

    return (rewritten, None) if changed else (None, None)


class Command(BaseCommand):
    help = "URL-encode the exception timestamp in error tracking alert deep links on existing destinations."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Update the destinations. The default is a dry run.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Number of matching destinations to read per page. The default is {DEFAULT_BATCH_SIZE}.",
        )

    def handle(self, *, live_run: bool, batch_size: int, **options: object) -> None:
        logger.setLevel(logging.INFO)
        if batch_size <= 0:
            raise CommandError("Batch size must be greater than zero.")

        queryset = (
            HogFunction.objects.filter(type="destination", deleted=False)
            .annotate(inputs_text=Cast("inputs", TextField()))
            .filter(inputs_text__contains=UNENCODED_TIMESTAMP)
            .order_by("id")
        )

        mode = "LIVE" if live_run else "DRY-RUN"
        matched = queryset.count()
        logger.info("alert_link_encoding_backfill_starting", mode=mode, matched=matched, batch_size=batch_size)

        updated = 0
        failed: list[tuple[str, int, str]] = []

        # A live run takes each updated row out of the queryset, so paginating the queryset itself
        # would skip every row that shifts onto a page already read. Resolve the ids up front and
        # page over those instead.
        matching_ids = list(queryset.values_list("id", flat=True))

        for batch_start in range(0, len(matching_ids), batch_size):
            batch = matching_ids[batch_start : batch_start + batch_size]
            for destination in HogFunction.objects.filter(id__in=batch):
                rewritten_inputs, error = rewrite_inputs(destination)
                if error is not None:
                    failed.append((str(destination.id), destination.team_id, error))
                    continue
                if rewritten_inputs is None:
                    continue
                updated += 1
                if live_run:
                    destination.inputs = rewritten_inputs
                    destination.save(update_fields=["inputs", "updated_at"])

        logger.info(
            "alert_link_encoding_backfill_complete",
            mode=mode,
            matched=matched,
            updated=updated,
            failed=len(failed),
        )
        for destination_id, team_id, error in failed:
            logger.warning(
                "alert_link_encoding_backfill_skipped", destination_id=destination_id, team_id=team_id, error=error
            )
