"""Local dev tool: send a single internal-referral invite email. DEBUG only.

Calls the same Celery task the Temporal activity uses (`send_internal_referral_invite_email`),
synchronously, so a green run here means the template renders + SMTP delivery is wired up
correctly against the local mailtrap / Maildev.
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.tasks.email import send_internal_referral_invite_email

logger = logging.getLogger(__name__)

DEFAULT_RECIPIENT = "test@posthog.com"


class Command(BaseCommand):
    help = "Local dev tool: send one internal-referral invite email via the real task. DEBUG only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            type=str,
            default=DEFAULT_RECIPIENT,
            help=f"Recipient email address (default: {DEFAULT_RECIPIENT})",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        recipient: str = options["to"]
        self.stdout.write(f"Recipient: {recipient}")
        self.stdout.write("")

        send_internal_referral_invite_email.apply(
            kwargs={"recipient_email": recipient, "enqueue_email_delivery": False},
            throw=True,
        )

        self.stdout.write(self.style.SUCCESS(f"Sent internal-referral invite to {recipient}"))
