from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from products.slack_app.backend.services.telegram_api import TelegramApiError, TelegramBotClient, telegram_config


class Command(BaseCommand):
    help = "Register this instance's Telegram webhook with the Bot API (setWebhook)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--url",
            default=None,
            help="Webhook base override (e.g. an ngrok URL in dev). Defaults to SITE_URL.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        config = telegram_config()
        secret = str(config["TELEGRAM_APP_WEBHOOK_SECRET"] or "")
        if not secret:
            raise CommandError("TELEGRAM_APP_WEBHOOK_SECRET is not configured")
        base = (options["url"] or settings.SITE_URL).rstrip("/")
        url = f"{base}/telegram/event-callback/"
        try:
            TelegramBotClient().set_webhook(url=url, secret_token=secret)
        except TelegramApiError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f"Telegram webhook set to {url}"))
