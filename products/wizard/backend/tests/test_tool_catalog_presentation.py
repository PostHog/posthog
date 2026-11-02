import json
from pathlib import Path

from unittest.mock import patch

from django.test import TestCase

from rest_framework import status

from products.wizard.backend.presentation.tool_catalog.serializers import WizardToolCatalogSerializer
from products.wizard.backend.tool_catalog import catalog


class TestWizardToolCatalogViewSet(TestCase):
    def setUp(self) -> None:
        catalog._catalog_document.cache_clear()
        catalog.tool_catalog_json.cache_clear()
        self.addCleanup(catalog._catalog_document.cache_clear)
        self.addCleanup(catalog.tool_catalog_json.cache_clear)

    def test_anonymous_client_gets_the_built_catalog_from_memory(self) -> None:
        text = json.dumps({"schema_version": catalog.CATALOG_SCHEMA_VERSION, "tools": []})
        with patch.object(catalog, "CATALOG_JSON") as catalog_file:
            catalog_file.exists.return_value = True
            catalog_file.read_text.return_value = text
            responses = [self.client.get("/api/wizard/tool_catalog/") for _ in range(2)]

        for response in responses:
            assert response.status_code == status.HTTP_200_OK
            assert response["Content-Type"] == "application/json"
            assert "public" in response["Cache-Control"]
            assert json.loads(response.content) == json.loads(text)
        assert catalog_file.read_text.call_count == 1

    def test_catalog_rendered_without_a_build_matches_the_documented_schema(self) -> None:
        with patch.object(catalog, "CATALOG_JSON", Path("/nonexistent/tool-catalog.json")):
            document = json.loads(self.client.get("/api/wizard/tool_catalog/").content)

        assert len(document["tools"]) > 0

        serializer = WizardToolCatalogSerializer(data=document)
        assert serializer.is_valid(), serializer.errors
        # is_valid() drops keys the serializer does not declare, so equality catches an undocumented field.
        assert serializer.validated_data == document
