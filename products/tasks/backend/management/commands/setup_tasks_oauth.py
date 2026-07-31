from django.core.management.base import BaseCommand

from posthog.models import OAuthApplication
from posthog.models.oauth import OAuthApplicationAuthBrand
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV, POSTHOG_AI_APP_CLIENT_ID_DEV
from posthog.utils import get_instance_region

ARRAY_REDIRECT_URIS = "http://localhost:8237/callback http://localhost:8239/callback"
POSTHOG_AI_REDIRECT_URIS = "http://localhost:8000/authorize"

# The apps created here carry the *_DEV client IDs, which `posthog.temporal.oauth` only ever
# looks up outside the production regions. Creating them in US/EU would add unused OAuth
# clients with localhost redirect URIs to a production database, so those regions are skipped
# rather than failed — `bin/migrate` runs this on every deploy.
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
