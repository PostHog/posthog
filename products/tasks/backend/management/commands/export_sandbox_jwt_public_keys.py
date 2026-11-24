import json

from django.core.management.base import BaseCommand

from products.tasks.backend.logic.services.connection_token import get_sandbox_jwt_public_key_bundle


class Command(BaseCommand):
    help = "Export the sandbox JWT verification keys as a kid-to-PEM JSON object"
    requires_system_checks: list[str] = []

    def handle(self, *args: str, **options: object) -> None:
        self.stdout.write(json.dumps(get_sandbox_jwt_public_key_bundle(), sort_keys=True))
