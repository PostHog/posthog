import ipaddress
from types import SimpleNamespace

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_EU, ARRAY_APP_CLIENT_ID_US

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.presentation.serializers import (
    TASK_RUN_ARTIFACT_INLINE_MAX_SIZE_BYTES,
    SandboxEnvironmentWriteSerializer,
    TaskRunArtifactUploadSerializer,
    TaskRunBootstrapCreateRequestSerializer,
    TaskRunCommandRequestSerializer,
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
            # These two resolve mintable gateway products, so a forged origin would reach
            # internally funded inference under a per-run cap.
            ("signals_chat", True),
            ("scout_suggestions", True),
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
    @parameterized.expand(
        [
            (TaskRunCreateRequestSerializer, True),
            (TaskRunCreateRequestSerializer, False),
            (TaskRunBootstrapCreateRequestSerializer, True),
            (TaskRunBootstrapCreateRequestSerializer, False),
        ]
    )
    def test_subscription_requires_acp(
        self,
        serializer_class: type[TaskRunCreateRequestSerializer] | type[TaskRunBootstrapCreateRequestSerializer],
        is_pi: bool,
    ) -> None:
        serializer = serializer_class(data={"claude_model_access": "own-subscription"})
        with patch("products.tasks.backend.presentation.serializers._is_pi_task_run_request", return_value=is_pi):
            assert serializer.is_valid() is not is_pi
        if is_pi:
            assert "claude_model_access" in serializer.errors

    @parameterized.expand(
        [
            (serializer_class, resume, client_id, sandbox)
            for serializer_class, resume in [
                (TaskRunCreateRequestSerializer, False),
                (TaskRunBootstrapCreateRequestSerializer, False),
                (TaskRunCreateRequestSerializer, True),
            ]
            for client_id in [ARRAY_APP_CLIENT_ID_US, ARRAY_APP_CLIENT_ID_EU]
            for sandbox in [False, True]
        ]
    )
    def test_subscription_checks_oauth_origin(self, serializer_class, resume, client_id, sandbox) -> None:
        authenticator = OAuthAccessTokenAuthentication()
        authenticator.access_token = OAuthAccessToken(
            application=OAuthApplication(client_id=client_id),
            scope="task:write internal_run:read" if sandbox else "task:write",
        )
        serializer = serializer_class(
            data={"resume_from_run_id": "00000000-0000-0000-0000-000000000001"}
            if resume
            else {"claude_model_access": "own-subscription"},
            context={
                "request": SimpleNamespace(successful_authenticator=authenticator),
                "view": SimpleNamespace(kwargs={"pk": "task-1"}),
                "team": SimpleNamespace(id=1),
            },
        )
        with patch.object(
            tasks_facade,
            "get_task_run_detail",
            return_value=SimpleNamespace(state={"claude_model_access": "own-subscription"}),
        ):
            assert serializer.is_valid() is (not sandbox and not resume), serializer.errors
        if sandbox or resume:
            assert "claude_model_access" in serializer.errors

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


class TestTaskRunArtifactUploadSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("at the ceiling", TASK_RUN_ARTIFACT_INLINE_MAX_SIZE_BYTES, True),
            ("above the ceiling", TASK_RUN_ARTIFACT_INLINE_MAX_SIZE_BYTES + 1, False),
        ]
    )
    def test_inline_content_is_capped_below_the_request_body_limit(
        self, _name: str, content_length: int, expected_valid: bool
    ) -> None:
        serializer = TaskRunArtifactUploadSerializer(
            data={
                "name": "output.txt",
                "type": "output",
                "content": "a" * content_length,
                "content_encoding": "utf-8",
            }
        )

        assert serializer.is_valid() is expected_valid
        if not expected_valid:
            megabytes = TASK_RUN_ARTIFACT_INLINE_MAX_SIZE_BYTES // (1024 * 1024)
            assert f"{megabytes}MB attachment limit" in str(serializer.errors["content"])


class TestCredentialResponseSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ({"token": ""},),
            ({"token": "x" * 4097},),
            ({"error": "arbitrary error body"},),
            ({"token": "invented-token", "error": "no_token"},),
            ({"credential": "unsupported", "token": "invented-token"},),
            ({"requestId": "x" * 129, "token": "invented-token"},),
        ]
    )
    def test_rejects_invalid_credential_response(self, params: dict[str, str]) -> None:
        serializer = TaskRunCommandRequestSerializer(
            data={
                "jsonrpc": "2.0",
                "method": "credential_response",
                "params": {"requestId": "request-1", "credential": "claude_subscription_token", **params},
            }
        )
        assert not serializer.is_valid()
        assert "params" in serializer.errors
