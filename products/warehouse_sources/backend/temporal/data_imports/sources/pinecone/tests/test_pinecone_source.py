from django.test import SimpleTestCase

import responses
from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pinecone import (
    PineconeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pinecone.source import PineconeSource


class TestPineconeCredentials(SimpleTestCase):
    @parameterized.expand(
        [
            ("valid_empty_project", 200, None, True, None),
            ("invalid_key", 401, None, False, "invalid or expired"),
            ("restricted_key_at_create", 403, None, True, None),
            ("invalid_key_for_table", 401, "backups", False, "invalid or expired"),
            ("missing_table_permission", 403, "backups", False, "key permissions and project plan"),
        ]
    )
    def test_validation_status(
        self, _name: str, status: int, schema_name: str | None, valid: bool, message: str | None
    ) -> None:
        path = "/backups" if schema_name else "/indexes"
        with responses.RequestsMock() as http:
            http.add(
                responses.GET,
                f"https://api.pinecone.io{path}",
                json={"data": []} if schema_name else {"indexes": []},
                status=status,
            )
            result, error = PineconeSource().validate_credentials(
                PineconeSourceConfig(api_key="fake-pinecone-key"), team_id=1, schema_name=schema_name
            )
            assert result is valid
            if message is None:
                assert error is None
            else:
                assert error is not None and message in error
            request = http.calls[0].request
            assert request.headers["Api-Key"] == "fake-pinecone-key"
            assert request.headers["X-Pinecone-Api-Version"] == "2026-07"
            assert request.url == f"https://api.pinecone.io{path}" + ("?limit=1" if schema_name else "")
            assert len(http.calls) == 1

    def test_unknown_table_is_rejected_without_http(self) -> None:
        with responses.RequestsMock() as http:
            valid, error = PineconeSource().validate_credentials(
                PineconeSourceConfig(api_key="fake-pinecone-key"), team_id=1, schema_name="vectors"
            )
            assert valid is False
            assert error is not None and "Unknown Pinecone table" in error
            assert len(http.calls) == 0

    def test_unexpected_client_error_propagates(self) -> None:
        with responses.RequestsMock() as http:
            http.add(responses.GET, "https://api.pinecone.io/indexes", json={"error": "bad_request"}, status=400)
            with self.assertRaises(HTTPError):
                PineconeSource().validate_credentials(PineconeSourceConfig(api_key="fake-pinecone-key"), team_id=1)
