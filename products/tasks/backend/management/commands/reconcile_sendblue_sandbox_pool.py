from django.core.management.base import BaseCommand

from products.tasks.backend.services.prewarmed_sandbox_pool import reconcile_sendblue_prewarmed_sandbox_pool


class Command(BaseCommand):
    help = "Reconcile the Sendblue prewarmed sandbox pool once."

    def handle(self, *args, **options):
        result = reconcile_sendblue_prewarmed_sandbox_pool()
        self.stdout.write(self.style.SUCCESS(f"Reconciled Sendblue sandbox pool: {result}"))
