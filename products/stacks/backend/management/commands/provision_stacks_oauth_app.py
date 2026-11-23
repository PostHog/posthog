from django.core.management.base import BaseCommand

from oauth2_provider.settings import oauth2_settings

from products.stacks.backend.facade import api


class Command(BaseCommand):
    help = (
        "Create or update the first-party OAuth application that stack runs mint their tokens from. "
        "Safe to run on every deploy."
    )

    def handle(self, *args, **options) -> None:
        # An OAuth application row does not validate without the OIDC signing key, as for the other first-party
        # applications `ensure_migration_defaults` seeds.
        if not oauth2_settings.OIDC_RSA_PRIVATE_KEY:
            self.stdout.write("Skipped the stacks OAuth application: no OIDC_RSA_PRIVATE_KEY is configured.")
            return
        client_id = api.provision_oauth_app()
        self.stdout.write(f"Stacks OAuth application {client_id} is set up.")
