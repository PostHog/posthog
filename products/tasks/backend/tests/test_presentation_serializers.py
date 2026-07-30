import ipaddress
from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.presentation.serializers import (
    SignalReportTaskCreateSerializer,
    TaskRunCreateRequestSerializer,
    TaskRunLivingArtifactCreateRequestSerializer,
    TaskWriteSerializer,
)
from products.tasks.backend.presentation.views.api import TaskViewSet


class TestTaskWriteSerializerOriginProduct(SimpleTestCase):
    @parameterized.expand(
        [
            ("image_builder", True),
            ("signals_scout", True),
            ("signal_report", True),
            ("user_created", False),
        ]
    )
    def test_internal_only_origins_are_rejected(self, origin_product: str, expected_rejected: bool) -> None:
        serializer = TaskWriteSerializer(data={"origin_product": origin_product})
        serializer.is_valid()
        assert ("origin_product" in serializer.errors) is expected_rejected
        if origin_product == "signal_report":
            assert serializer.errors["origin_product"][0] == (
                "Update the PostHog app to create Signal Report tasks, then try again."
            )

    def test_signal_report_serializer_assigns_origin(self) -> None:
        serializer = SignalReportTaskCreateSerializer()
        assert serializer.fields["origin_product"].default == "signal_report"


class TestTaskWriteTelemetry(SimpleTestCase):
    @patch("products.tasks.backend.presentation.views.api.logger.info")
    def test_logs_client_attribution_before_validation(self, info: MagicMock) -> None:
        view = TaskViewSet()
        view.team = SimpleNamespace(id=123)
        view.request = SimpleNamespace(user=SimpleNamespace(id=456))
        serializer = MagicMock()
        serializer_class = MagicMock(return_value=serializer)

        result = view._write_serializer(
            {"origin_product": "signal_report", "internal": True},
            serializer_class=serializer_class,
        )

        assert result is serializer
        info.assert_called_once_with(
            "task_api_client_attribution",
            extra={
                "team_id": 123,
                "user_id": 456,
                "origin_product": "signal_report",
                "internal": True,
            },
        )
        serializer.is_valid.assert_called_once_with(raise_exception=True)


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
