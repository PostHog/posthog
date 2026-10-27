from typing import Any

from django.core.management.base import BaseCommand

from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
    CLASSIFICATION_AUDIT_PATH,
    render_classification_audit,
)


class Command(BaseCommand):
    help = (
        "Write the audit table of which job_inputs keys of each warehouse source are connection fields, "
        "sync settings or runtime state. A test fails when the committed table is out of date."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        CLASSIFICATION_AUDIT_PATH.write_text(render_classification_audit())
        self.stdout.write(self.style.SUCCESS(f"Wrote {CLASSIFICATION_AUDIT_PATH}"))
