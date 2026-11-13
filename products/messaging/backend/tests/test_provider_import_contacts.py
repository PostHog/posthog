import json

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.provider_imports import contacts
from products.messaging.backend.provider_imports.base import ImportTooLarge
from products.messaging.backend.provider_imports.contacts import ContactCollector
from products.workflows.backend.facade.people_import import MAX_PEOPLE_IMPORT_ROW_BYTES


class TestContactCollector(SimpleTestCase):
    @parameterized.expand(
        [
            ("many_fields", {f"field_{i}": "x" * 900 for i in range(10)}),
            # JSON escapes each é as six bytes, so 700 of them pass a byte count of the text and still don't fit.
            ("accented_field", {"first_name": "é" * 700, "last_name": "Lovelace"}),
        ]
    )
    def test_a_contact_keeps_only_the_properties_that_fit_one_row(self, _name: str, properties: dict) -> None:
        collector = ContactCollector()

        row = collector.add("ada@example.com", properties)
        merged = collector.add("ADA@example.com", {"plan": "pro", **{f"more_{i}": "y" * 900 for i in range(5)}})

        assert merged is row
        assert row is not None and row["plan"] == "pro"
        assert len(json.dumps(row).encode()) <= MAX_PEOPLE_IMPORT_ROW_BYTES

    def test_too_much_contact_data_stops_the_step_for_good(self) -> None:
        collector = ContactCollector()

        with patch.object(contacts, "MAX_CONTACT_BYTES", 10_000), self.assertRaises(ImportTooLarge):
            for i in range(100):
                collector.add(f"person{i}@example.com", {"bio": "z" * 500})
