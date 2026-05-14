"""Local dev tool for verifying the X DM client end-to-end. DEBUG only.

Sends a single 1:1 DM via the same `send_referral_dms` path the Temporal activity uses,
so a green run here means the OAuth refresh + handle lookup + DM POST are all wired
correctly on this worker / env.

Requires `X_CLIENT_ID`, `X_CLIENT_SECRET`, `X_REFRESH_TOKEN` in the shell environment.
"""

import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from products.referrals.backend.twitter.x_dm import reset_refresh_token_cache, send_referral_dms

logger = logging.getLogger(__name__)

DEFAULT_HANDLE = "yo_puaaa"
DEFAULT_TEXT = "hey, Matt, what's up?"


class Command(BaseCommand):
    help = "Local dev tool: send one test DM via the X v2 API. DEBUG only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--handle",
            type=str,
            default=DEFAULT_HANDLE,
            help=f"Twitter/X handle to DM, without leading @ (default: {DEFAULT_HANDLE})",
        )
        parser.add_argument(
            "--text",
            type=str,
            default=DEFAULT_TEXT,
            help=f"DM body (default: {DEFAULT_TEXT!r})",
        )
        parser.add_argument(
            "--reset-cache",
            action="store_true",
            help="Clear the Django-cached rotated refresh token before running; forces fall-back to X_REFRESH_TOKEN env var.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        # Surface x_dm INFO/WARNING logs to stdout so per-step status is visible.
        x_dm_logger = logging.getLogger("products.referrals.backend.twitter.x_dm")
        x_dm_logger.setLevel(logging.INFO)
        if not any(isinstance(h, logging.StreamHandler) for h in x_dm_logger.handlers):
            x_dm_logger.addHandler(logging.StreamHandler())

        if options["reset_cache"]:
            reset_refresh_token_cache()
            self.stdout.write(self.style.WARNING("Cleared cached refresh token; will use X_REFRESH_TOKEN from env."))

        handle: str = options["handle"]
        text: str = options["text"]

        self.stdout.write(f"Recipient: @{handle}")
        self.stdout.write(f"Message:   {text!r}")
        self.stdout.write("")

        summary = asyncio.run(send_referral_dms([(handle, text)]))

        self.stdout.write("")
        line = f"sent={summary.sent} failed_lookup={summary.failed_lookup} failed_send={summary.failed_send}"
        self.stdout.write(self.style.SUCCESS(line) if summary.sent else self.style.ERROR(line))
