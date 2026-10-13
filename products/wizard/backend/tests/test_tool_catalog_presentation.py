import json

from unittest.mock import patch

from django.test import TestCase

from rest_framework import status

from products.wizard.backend.tool_catalog import catalog


class TestWizardToolCatalogViewSet(TestCase):
    def setUp(self) -> None:
        catalog._catalog_document.cache_clear()
        catalog.tool_catalog_json.cache_clear()
        self.addCleanup(catalog._catalog_document.cache_clear)
        self.addCleanup(catalog.tool_catalog_json.cache_clear)

    def test_anonymous_client_gets_the_generated_catalog_from_memory(self) -> None:
        text = catalog.CATALOG_JSON.read_text()
        with patch.object(catalog, "CATALOG_JSON") as catalog_file:
            catalog_file.read_text.return_value = text
            responses = [self.client.get("/api/wizard/tool_catalog/") for _ in range(2)]

        for response in responses:
            assert response.status_code == status.HTTP_200_OK
            assert response["Content-Type"] == "application/json"
            assert "public" in response["Cache-Control"]
            assert json.loads(response.content) == json.loads(text)
        assert catalog_file.read_text.call_count == 1
