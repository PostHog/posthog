import json
from typing import Any

from unittest import TestCase
from unittest.mock import MagicMock, patch

from products.cohorts.backend.models.cohort import Cohort

_TASKS = "products.workflows.backend.tasks.people_import"


class PeopleImportRecorder:
    """Stands in for the people import's storage and tasks, and records what each import would send or fill."""

    def __init__(self, test: TestCase) -> None:
        self.stored: dict[str, str] = {}
        self.storage = MagicMock()
        self.storage.write.side_effect = self.stored.__setitem__
        # ("send <cohort>" or "fill <cohort>", distinct IDs), in the order the imports started.
        self.imports: list[tuple[str, list[str]]] = []
        # The person properties the sending import sets, by distinct ID.
        self.properties: dict[str, dict[str, str]] = {}
        for target, kwargs in (
            ("products.workflows.backend.services.people_import.object_storage", {"new": self.storage}),
            (f"{_TASKS}.capture_people_import.delay", {"side_effect": lambda **kw: self._record(True, kw)}),
            (f"{_TASKS}.schedule_people_import_fill", {"side_effect": lambda **kw: self._record(False, kw)}),
            (f"{_TASKS}.fail_people_import_if_stalled.apply_async", {}),
        ):
            patcher = patch(target, **kwargs)
            test.addCleanup(patcher.stop)
            patcher.start()

    def _record(self, sends: bool, kwargs: dict[str, Any]) -> None:
        people = json.loads(self.stored[kwargs["storage_key"]])
        cohort = Cohort.objects.get(id=kwargs["cohort_id"])
        self.imports.append((f"{'send' if sends else 'fill'} {cohort.name}", [p["distinct_id"] for p in people]))
        if sends:
            self.properties.update({person["distinct_id"]: person["properties"] for person in people})
