import json

from unittest.mock import patch

from django.test import SimpleTestCase

from products.messaging.backend.provider_imports import contacts
from products.messaging.backend.provider_imports.base import ImportStepError
from products.messaging.backend.provider_imports.contacts import ContactCollector
from products.workflows.backend.facade.people_import import MAX_PEOPLE_IMPORT_ROW_BYTES


class TestContactCollector(SimpleTestCase):
    def test_a_contact_keeps_only_the_properties_that_fit_one_row(self) -> None:
        collector = ContactCollector()

        row = collector.add("ada@example.com", {f"field_{i}": "x" * 900 for i in range(10)})
        merged = collector.add("ADA@example.com", {"plan": "pro", **{f"more_{i}": "y" * 900 for i in range(5)}})

        assert merged is row
        assert row is not None and row["plan"] == "pro"
        assert len(json.dumps(row).encode()) <= MAX_PEOPLE_IMPORT_ROW_BYTES

    def test_too_much_contact_data_stops_the_step(self) -> None:
        collector = ContactCollector()

        with patch.object(contacts, "MAX_CONTACT_BYTES", 10_000), self.assertRaises(ImportStepError):
            for i in range(100):
                collector.add(f"person{i}@example.com", {"bio": "z" * 500})
