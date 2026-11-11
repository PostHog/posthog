import json
from pathlib import Path

import pytest
from unittest.mock import patch

from django.test import TestCase

from rest_framework import status

from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.wizard.backend.presentation.tool_catalog.serializers import WizardToolCatalogSerializer
from products.wizard.backend.tool_catalog import catalog
from products.wizard.backend.tool_catalog.posthog_alternatives import POSTHOG_ALTERNATIVES_WITHOUT_SOURCE
from products.wizard.backend.tool_catalog.warehouse_destinations import (
    CATALOG_DESTINATION_CHOICES,
    WAREHOUSE_DESTINATION_BY_KIND,
    warehouse_destination_type,
)


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


@pytest.fixture
def rendered_tools() -> dict[str, dict]:
    document = catalog.build_catalog_document()
    return {tool["kind"]: tool for tool in document["tools"]}


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("Postgres", None),
        ("BigQuery", "BigQuery"),
        ("Snowflake", "Snowflake"),
        ("Redshift", "Redshift"),
        ("Databricks", "Databricks"),
        ("AmazonS3", "S3"),
        ("AzureBlob", "AzureBlob"),
        ("Supabase", None),
        ("Neon", None),
        ("Stripe", None),
        ("not-a-kind", None),
    ],
)
def test_warehouse_destination_type_by_kind(kind: str, expected: str | None) -> None:
    assert warehouse_destination_type(kind) == expected


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("Postgres", None),
        ("BigQuery", "BigQuery"),
        ("Snowflake", "Snowflake"),
        ("Redshift", "Redshift"),
        ("Databricks", "Databricks"),
        ("AmazonS3", "S3"),
        ("AzureBlob", "AzureBlob"),
        ("Supabase", None),
        ("Neon", None),
    ],
)
def test_rendered_document_emits_destination_type(
    rendered_tools: dict[str, dict], kind: str, expected: str | None
) -> None:
    if kind not in rendered_tools:
        pytest.skip(f"{kind} has no codebase detection")
    assert rendered_tools[kind]["warehouse_destination_type"] == expected


def test_every_tool_emits_the_field_with_a_valid_value(rendered_tools: dict[str, dict]) -> None:
    valid = {value for value, _ in CATALOG_DESTINATION_CHOICES}
    assert len(valid) == 7
    for tool in rendered_tools.values():
        assert "warehouse_destination_type" in tool
        assert tool["warehouse_destination_type"] is None or tool["warehouse_destination_type"] in valid


def test_posthog_alternatives_have_no_destination_type(rendered_tools: dict[str, dict]) -> None:
    assert POSTHOG_ALTERNATIVES_WITHOUT_SOURCE
    for kind in POSTHOG_ALTERNATIVES_WITHOUT_SOURCE:
        assert rendered_tools[kind]["warehouse_destination_type"] is None


def test_mapped_kinds_are_known_source_types() -> None:
    source_values = {source_type.value for source_type in ExternalDataSourceType}
    assert set(WAREHOUSE_DESTINATION_BY_KIND) <= source_values
