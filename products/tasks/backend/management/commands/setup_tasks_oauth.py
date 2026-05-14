from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import OAuthApplication
from posthog.temporal.oauth import POSTHOG_CODE_OAUTH_CLIENT_ID_DEV


class Command(BaseCommand):
    help = "Create the PostHog Code OAuth application for local cloud runs development"

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=1")

        app, created = OAuthApplication.objects.get_or_create(
            client_id=POSTHOG_CODE_OAUTH_CLIENT_ID_DEV,
            defaults={
                "name": "PostHog Code Dev App",
                "client_type": OAuthApplication.CLIENT_PUBLIC,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": "http://localhost:8237/callback http://localhost:8239/callback",
                "algorithm": "RS256",
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created OAuthApplication '{app.name}' (client_id={app.client_id})"))
        else:
            self.stdout.write(self.style.SUCCESS(f"OAuthApplication '{app.name}' already exists"))
