from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import OAuthApplication
from posthog.models.oauth import OAuthApplicationAuthBrand
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV, POSTHOG_AI_APP_CLIENT_ID_DEV

ARRAY_REDIRECT_URIS = "http://localhost:8237/callback http://localhost:8239/callback"
POSTHOG_AI_REDIRECT_URIS = "http://localhost:8000/authorize"


class Command(BaseCommand):
    help = "Create the Array OAuth application for local cloud runs development"

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=1")

        self._setup_app(
            ARRAY_APP_CLIENT_ID_DEV,
            {
                "name": "Array Dev App",
                "client_type": OAuthApplication.CLIENT_PUBLIC,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": ARRAY_REDIRECT_URIS,
                "algorithm": "RS256",
            },
        )
        self._setup_app(
            POSTHOG_AI_APP_CLIENT_ID_DEV,
            {
                "name": "PostHog AI Dev App",
                "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": POSTHOG_AI_REDIRECT_URIS,
                "algorithm": "RS256",
                "auth_brand": OAuthApplicationAuthBrand.POSTHOG.value,
                "is_verified": True,
                "is_first_party": True,
            },
        )

    def _setup_app(self, client_id: str, defaults: dict[str, object]) -> None:
        if not client_id:
            self.stdout.write(self.style.WARNING(f"Skipping {defaults['name']}; no client_id configured"))
            return

        app, created = OAuthApplication.objects.get_or_create(
            client_id=client_id,
            defaults=defaults,
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created OAuthApplication '{app.name}' (client_id={app.client_id})"))
        else:
            self.stdout.write(self.style.SUCCESS(f"OAuthApplication '{app.name}' already exists"))
