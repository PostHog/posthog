from django.core.management.base import BaseCommand

from products.stacks.backend.facade import api


class Command(BaseCommand):
    help = "Re-encrypt every stack record and saved diff onto the first key in STACKS_ENCRYPTION_KEYS."

    def handle(self, *args, **options) -> None:
        rewritten = api.reencrypt_records()
        self.stdout.write(f"Re-encrypted {rewritten} rows.")
