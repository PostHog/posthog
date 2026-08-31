from products.tasks.backend.temporal import ACTIVITIES
from products.tasks.backend.temporal.process_task.activities.export_draft_publication_bundle import (
    export_draft_publication_bundle,
)


def test_registers_staged_draft_publication_export_activity() -> None:
    assert export_draft_publication_bundle in ACTIVITIES
