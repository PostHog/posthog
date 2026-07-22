import ipaddress

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.models import Task
from products.tasks.backend.presentation.serializers import (
    API_CREATABLE_ORIGIN_PRODUCTS,
    TaskCreateSerializer,
    TaskRunCreateRequestSerializer,
    TaskRunLivingArtifactCreateRequestSerializer,
    TaskWriteSerializer,
)

_RESERVED_ORIGIN_MESSAGES = {
    "image_builder": "origin_product 'image_builder' is reserved for image-builder sessions",
    "experiments": "origin_product 'experiments' is reserved for the experiments flow",
}


class TestTaskOriginProductValidation(SimpleTestCase):
    @parameterized.expand(
        [(value,) for value in sorted(set(Task.OriginProduct.values) - API_CREATABLE_ORIGIN_PRODUCTS)]
    )
    def test_create_rejects_reserved_origin(self, origin: str) -> None:
        serializer = TaskCreateSerializer(data={"origin_product": origin})

        assert not serializer.is_valid()
        expected = _RESERVED_ORIGIN_MESSAGES.get(origin, f"origin_product '{origin}' is reserved for server-side flows")
        assert str(serializer.errors["origin_product"][0]) == expected

    @parameterized.expand([(value,) for value in sorted(API_CREATABLE_ORIGIN_PRODUCTS)])
    def test_create_accepts_client_origin(self, origin: str) -> None:
        serializer = TaskCreateSerializer(data={"origin_product": origin})

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["origin_product"] == origin

    def test_update_rejects_origin_product(self) -> None:
        serializer = TaskWriteSerializer(data={"origin_product": Task.OriginProduct.USER_CREATED}, partial=True)

        assert not serializer.is_valid()
        assert str(serializer.errors["origin_product"][0]) == "origin_product cannot be changed after task creation."


class TestTaskRunLivingArtifactCreateRequestSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("blank_content", {"name": "canvas", "content": ""}, True),
            ("content_and_source", {"name": "canvas", "content": "hi", "source_artifact_id": "artifact-1"}, False),
        ]
    )
    def test_content_source_exclusivity(self, _name: str, data: dict, expected_valid: bool) -> None:
        serializer = TaskRunLivingArtifactCreateRequestSerializer(data=data)
        assert serializer.is_valid() is expected_valid


class TestTaskRunCreateRequestSerializer(SimpleTestCase):
    @patch(
        "posthog.security.url_validation.resolve_host_ips",
        return_value={ipaddress.ip_address("93.184.216.34")},
    )
    def test_deduplicates_imported_mcp_server_host_resolution(self, mock_resolve_host_ips) -> None:
        serializer = TaskRunCreateRequestSerializer(
            data={
                "environment": "cloud",
                "imported_mcp_servers": [
                    {"type": "http", "name": "first", "url": "https://shared.example.com/first"},
                    {"type": "http", "name": "second", "url": "https://shared.example.com/second"},
                ],
            }
        )

        assert serializer.is_valid(), serializer.errors
        mock_resolve_host_ips.assert_called_once_with("shared.example.com")

    @patch("products.tasks.backend.presentation.serializers.resolve_url_hosts_ips")
    def test_rejects_too_many_imported_mcp_servers_before_dns_resolution(self, mock_resolve_url_hosts_ips) -> None:
        serializer = TaskRunCreateRequestSerializer(
            data={
                "environment": "cloud",
                "imported_mcp_servers": [
                    {"type": "http", "name": f"server-{index}", "url": f"https://{index}.example.com"}
                    for index in range(21)
                ],
            }
        )

        assert not serializer.is_valid()
        mock_resolve_url_hosts_ips.assert_not_called()
