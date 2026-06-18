from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import OAuthApplication
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

EXPECTED_REDIRECT_URIS = "http://localhost:8237/callback http://localhost:8239/callback"


class Command(BaseCommand):
    help = "Create the Array OAuth application for local cloud runs development"

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=1")

        self._setup_app(ARRAY_APP_CLIENT_ID_DEV, "Array Dev App")
        self._setup_app(settings.POSTHOG_AI_APP_CLIENT_ID_DEV, "PostHog AI Dev App")

    def _setup_app(self, client_id: str, name: str) -> None:
        if not client_id:
            self.stdout.write(self.style.WARNING(f"Skipping {name}; no client_id configured"))
            return

        app, created = OAuthApplication.objects.get_or_create(
            client_id=client_id,
            defaults={
                "name": name,
                "client_type": OAuthApplication.CLIENT_PUBLIC,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": EXPECTED_REDIRECT_URIS,
                "algorithm": "RS256",
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created OAuthApplication '{app.name}' (client_id={app.client_id})"))
        else:
            self.stdout.write(self.style.SUCCESS(f"OAuthApplication '{app.name}' already exists"))
