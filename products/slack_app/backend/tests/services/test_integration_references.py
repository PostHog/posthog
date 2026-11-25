from django.test import SimpleTestCase

from parameterized import parameterized

from products.slack_app.backend.services.integration_references import read_integration_id, store_integration_id


class TestIntegrationReferences(SimpleTestCase):
    @parameterized.expand(
        [
            ("legacy_id", "53", 53),
            ("uuid_from_the_credentials_service", "0b6f3c1e-8a2d-4c6e-9f1a-2d3e4f5a6b7c", None),
            ("malformed", "not-a-reference", None),
            ("empty", None, None),
        ]
    )
    def test_read(self, _name: str, stored: str | None, expected: int | None) -> None:
        assert read_integration_id(stored) == expected

    def test_round_trip(self) -> None:
        assert read_integration_id(store_integration_id(53)) == 53
        assert store_integration_id(None) is None
