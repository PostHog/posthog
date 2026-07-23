import ipaddress

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.presentation.serializers import (
    TaskRunCreateRequestSerializer,
    TaskRunLivingArtifactCreateRequestSerializer,
)


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
