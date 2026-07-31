from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.slack_app.backend.services.whatsapp_api import WhatsAppApiError, WhatsAppBotClient


class Command(BaseCommand):
    help = (
        "Subscribe the Meta app to the WhatsApp Business Account's webhook events. "
        "The webhook URL and verify token are configured in the Meta App Dashboard; "
        "this completes the API-side subscription that turns delivery on."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--waba-id",
            required=True,
            help="WhatsApp Business Account id (from Meta Business Manager).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            WhatsAppBotClient().subscribe_app(waba_id=options["waba_id"])
        except WhatsAppApiError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f"App subscribed to WABA {options['waba_id']}"))
