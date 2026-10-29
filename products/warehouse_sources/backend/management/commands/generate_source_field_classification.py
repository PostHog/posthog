from typing import Any

from django.core.management.base import BaseCommand

from products.warehouse_sources.backend.temporal.data_imports.sources.common.credential_kind import (
    CREDENTIAL_KINDS_PATH,
    render_credential_kinds,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
    CLASSIFICATION_AUDIT_PATH,
    render_classification_audit,
)


class Command(BaseCommand):
    help = (
        "Write the audit table of which job_inputs keys of each warehouse source are connection fields, "
        "references, selectors, sync settings or runtime state, and write the frozen credential kind of "
        "each source. A test fails when either committed file is out of date."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        CREDENTIAL_KINDS_PATH.write_text(render_credential_kinds())
        self.stdout.write(self.style.SUCCESS(f"Wrote {CREDENTIAL_KINDS_PATH}"))
        CLASSIFICATION_AUDIT_PATH.write_text(render_classification_audit())
        self.stdout.write(self.style.SUCCESS(f"Wrote {CLASSIFICATION_AUDIT_PATH}"))
