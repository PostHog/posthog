from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import OAuthApplication
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV


class Command(BaseCommand):
    help = "Create the Array OAuth application for local cloud runs development"

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=1")

        app, created = OAuthApplication.objects.get_or_create(
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            defaults={
                "name": "Array Dev App",
                "client_type": OAuthApplication.CLIENT_PUBLIC,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": "https://app.posthog.com/callback",
                "algorithm": "RS256",
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created OAuthApplication '{app.name}' (client_id={app.client_id})"))
        else:
            self.stdout.write(self.style.SUCCESS(f"OAuthApplication '{app.name}' already exists"))
