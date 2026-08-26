import ipaddress

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.presentation.serializers import (
    SandboxEnvironmentWriteSerializer,
    TaskRunCreateRequestSerializer,
    TaskRunLivingArtifactCreateRequestSerializer,
    TaskWriteSerializer,
)


class TestSandboxEnvironmentWriteSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("scheme", "https://example.com"),
            ("path", "example.com/path"),
            ("port", "example.com:443"),
            ("ip", "127.0.0.1"),
            ("malformed_wildcard", "api.*.example.com"),
        ]
    )
    def test_rejects_domains_that_cannot_be_enforced(self, _name: str, domain: str) -> None:
        serializer = SandboxEnvironmentWriteSerializer(data={"name": "Restricted", "allowed_domains": [domain]})

        assert not serializer.is_valid()
        assert "allowed_domains" in serializer.errors

    def test_normalizes_valid_domains(self) -> None:
        serializer = SandboxEnvironmentWriteSerializer(
            data={"name": "Restricted", "allowed_domains": [" EXAMPLE.com ", "example.com"]}
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["allowed_domains"] == ["example.com"]

    def test_rejects_too_many_allowed_domains(self) -> None:
        domains = [f"host-{index}.example.com" for index in range(tasks_facade.MAX_SANDBOX_ALLOWED_DOMAINS + 1)]
        serializer = SandboxEnvironmentWriteSerializer(data={"name": "Restricted", "allowed_domains": domains})

        assert not serializer.is_valid()
        assert serializer.errors["allowed_domains"][0].code == "max_length"

    def test_facade_rejects_too_many_allowed_domains(self) -> None:
        domains = [f"host-{index}.example.com" for index in range(tasks_facade.MAX_SANDBOX_ALLOWED_DOMAINS + 1)]

        with self.assertRaisesRegex(ValueError, "You can allow up to 100 domains"):
            tasks_facade.normalize_sandbox_allowed_domains(domains)


class TestTaskWriteSerializerOriginProduct(SimpleTestCase):
    @parameterized.expand(
        [
            ("image_builder", True),
            ("signals_scout", True),
            ("user_created", False),
        ]
    )
    def test_internal_only_origins_are_rejected(self, origin_product: str, expected_rejected: bool) -> None:
        serializer = TaskWriteSerializer(data={"origin_product": origin_product})
        serializer.is_valid()
        assert ("origin_product" in serializer.errors) is expected_rejected


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
