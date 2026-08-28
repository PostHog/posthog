from django.core.management.base import BaseCommand

from posthog.models import OAuthApplication
from posthog.models.oauth import OAuthApplicationAuthBrand
from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_DEV,
    ARRAY_APP_ID_DEV,
    POSTHOG_AI_APP_CLIENT_ID_DEV,
    POSTHOG_AI_APP_ID_DEV,
    SIGNALS_APP_CLIENT_ID_DEV,
    SIGNALS_APP_ID_DEV,
)
from posthog.utils import get_instance_region

ARRAY_REDIRECT_URIS = "http://localhost:8237/callback http://localhost:8239/callback"
POSTHOG_AI_REDIRECT_URIS = "http://localhost:8000/authorize"
# Server-minted only: no interactive grant is ever issued against the Signals app, so it has
# no real callback. Django requires a redirect URI for the authorization-code grant type.
SIGNALS_REDIRECT_URIS = "http://localhost:8000/authorize"

# Skipped rather than failed, so the unconditional call in bin/migrate is safe.
PRODUCTION_REGIONS = frozenset({"US", "EU"})


class Command(BaseCommand):
    help = "Create the Array and PostHog AI OAuth applications task sandboxes mint tokens under"

    def handle(self, *args, **options):
        region = get_instance_region()
        if region in PRODUCTION_REGIONS:
            self.stdout.write(f"Skipping dev OAuth application setup; region {region} has its own applications")
            return

        self._setup_app(
            ARRAY_APP_CLIENT_ID_DEV,
            {
                "id": ARRAY_APP_ID_DEV,
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
                "id": POSTHOG_AI_APP_ID_DEV,
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
        self._setup_app(
            SIGNALS_APP_CLIENT_ID_DEV,
            {
                "id": SIGNALS_APP_ID_DEV,
                "name": "Signals Dev App",
                "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": SIGNALS_REDIRECT_URIS,
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
            return

        self.stdout.write(self.style.SUCCESS(f"OAuthApplication '{app.name}' already exists"))
        # Not repaired here: changing the pk means deleting the row, cascading to its tokens.
        if str(app.id) != defaults["id"]:
            self.stdout.write(
                self.style.WARNING(
                    f"  '{app.name}' has id {app.id}, expected {defaults['id']}. The LLM gateway "
                    "authorizes by application id, so tokens minted under it will be rejected."
                )
            )
