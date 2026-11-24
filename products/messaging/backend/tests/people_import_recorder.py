import json
from typing import Any

from unittest import TestCase
from unittest.mock import MagicMock, patch

from posthog.api.capture import CaptureInternalResult

_SERVICE = "products.workflows.backend.services.provider_contacts"


class PeopleImportRecorder:
    """Stands in for object storage and capture, and records the contact lists an import stores and the events it
    sends."""

    def __init__(self, test: TestCase) -> None:
        self.stored: dict[str, str] = {}
        storage = self.storage = MagicMock()
        storage.write.side_effect = self.stored.__setitem__
        storage.read.side_effect = lambda key, missing_ok=False: self.stored.get(key)
        storage.iter_keys.side_effect = lambda prefix: [key for key in list(self.stored) if key.startswith(prefix)]
        storage.delete_objects.side_effect = lambda keys: [self.stored.pop(key) for key in keys] and []
        self.events: list[dict[str, Any]] = []
        self.capture_refuses = False
        for target, kwargs in (
            ("products.workflows.backend.services.people_import.object_storage", {"new": storage}),
            (f"{_SERVICE}.object_storage", {"new": storage}),
            (f"{_SERVICE}.capture_batch_internal", {"side_effect": self._capture}),
        ):
            patcher = patch(target, **kwargs)
            test.addCleanup(patcher.stop)
            patcher.start()

    def people(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        """The people a stored list holds, from a plan in the step's progress."""
        return [
            person
            for chunk in range(plan["chunks"])
            for person in json.loads(self.stored[f"{plan['storage_prefix']}/chunk-{chunk}.json"])
        ]

    def _capture(self, *, events: list[dict[str, Any]], **_: Any) -> CaptureInternalResult:
        uuids = [event["event_uuid"] for event in events]
        if self.capture_refuses:
            return CaptureInternalResult(status_code=0, unaccounted=uuids)
        self.events.extend(events)
        return CaptureInternalResult(status_code=200, ok=uuids)
