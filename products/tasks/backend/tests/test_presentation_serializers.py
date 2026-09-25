import ipaddress
from types import SimpleNamespace

import time_machine
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_EU,
    ARRAY_APP_CLIENT_ID_US,
    POSTHOG_DESKTOP_MOBILE_APP_CLIENT_ID_US,
)

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.model_catalogue import GatewayModel
from products.tasks.backend.presentation.serializers import (
    TASK_RUN_ARTIFACT_INLINE_MAX_SIZE_BYTES,
    SandboxEnvironmentWriteSerializer,
    TaskCreateSerializer,
    TaskRunArtifactUploadSerializer,
    TaskRunBootstrapCreateRequestSerializer,
    TaskRunCommandRequestSerializer,
    TaskRunCreateRequestSerializer,
    TaskRunLivingArtifactCreateRequestSerializer,
    TaskRunUpdateSerializer,
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
    @time_machine.travel("2026-09-18T12:00:00Z", tick=False)
    def test_schedule_requires_start_run(self) -> None:
        serializer = TaskCreateSerializer(data={"scheduled_at": "2026-09-19T12:00:00Z"})
        assert not serializer.is_valid()
        assert "scheduled_at" in serializer.errors

    @parameterized.expand(
        [
            ("utc", "2026-09-19T12:00:00Z", "2026-09-19T12:00:00+00:00"),
            ("offset", "2026-09-19T14:00:00+02:00", "2026-09-19T12:00:00+00:00"),
            ("no_offset", "2026-09-19T12:00:00", "2026-09-19T12:00:00+00:00"),
            ("limit", "2026-10-18T12:00:00Z", "2026-10-18T12:00:00+00:00"),
            ("now", "2026-09-18T12:00:00Z", None),
            ("past", "2026-09-17T12:00:00Z", None),
            ("too_far", "2026-10-18T12:00:01Z", None),
            ("invalid", "tomorrow", None),
        ]
    )
    @time_machine.travel("2026-09-18T12:00:00Z", tick=False)
    def test_schedule_window(self, _name: str, scheduled_at: str, expected: str | None) -> None:
        for serializer_class in (TaskRunCreateRequestSerializer, TaskCreateSerializer):
            serializer = serializer_class(data={"scheduled_at": scheduled_at, "start_run": True})
            with django_timezone.override("America/New_York"):
                assert serializer.is_valid() is (expected is not None), serializer.errors
            if expected is None:
                assert "scheduled_at" in serializer.errors
            else:
                assert serializer.validated_data["scheduled_at"].isoformat() == expected

    @parameterized.expand(
        [
            ("interactive", {"mode": "interactive"}, "scheduled_at"),
            ("pi", {}, "scheduled_at"),
            ("token", {"github_user_token": "test-token"}, "github_user_token"),
            (
                "imported",
                {"imported_mcp_servers": [{"type": "http", "name": "example", "url": "https://example.com"}]},
                "imported_mcp_servers",
            ),
        ]
    )
    @time_machine.travel("2026-09-18T12:00:00Z", tick=False)
    @patch("posthog.security.url_validation.resolve_host_ips", return_value={ipaddress.ip_address("93.184.216.34")})
    def test_schedule_rejects_unsupported_inputs(self, name: str, payload: dict, field: str, _resolve_host_ips) -> None:
        serializer = TaskRunCreateRequestSerializer(data={"scheduled_at": "2026-09-19T12:00:00", **payload})
        with patch(
            "products.tasks.backend.presentation.serializers._is_pi_task_run_request", return_value=name == "pi"
        ):
            assert not serializer.is_valid()
        assert field in serializer.errors

    @parameterized.expand(
        [
            ("gpt-5.3-codex", "high", "codex"),
            ("claude-sonnet-4-6", "medium", "claude"),
            ("unknown-model", "high", None),
            ("gpt-5.3-codex", "ultracode", None),
        ]
    )
    @patch(
        "products.tasks.backend.logic.services.model_catalogue.list_gateway_models",
        return_value=(GatewayModel(id="gpt-5.3-codex", owned_by="openai", context_window=200_000),),
    )
    def test_model_only_selection(self, model: str, effort: str, adapter: str | None, _models) -> None:
        serializer = TaskRunCreateRequestSerializer(data={"model": model, "reasoning_effort": effort})
        assert serializer.is_valid() is (adapter is not None), serializer.errors
        if adapter is not None:
            assert serializer.validated_data["runtime_adapter"] == adapter

    @parameterized.expand([([],), ([["run_source", "manual"]],), (None,), ("manual",), (1,), (False,)])
    def test_rejects_non_object_run_state(self, state):
        serializer = TaskRunUpdateSerializer(data={"state": state})
        assert not serializer.is_valid()
        assert "state" in serializer.errors

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
            (serializer_class, resume, caller)
            for serializer_class, resume in [
                (TaskRunCreateRequestSerializer, False),
                (TaskRunBootstrapCreateRequestSerializer, False),
                (TaskRunCreateRequestSerializer, True),
            ]
            for caller in ["desktop_us", "desktop_eu", "mobile", "sandbox", "session"]
        ]
    )
    def test_subscription_checks_oauth_origin(self, serializer_class, resume, caller) -> None:
        authenticator = None
        if caller != "session":
            authenticator = OAuthAccessTokenAuthentication()
            authenticator.access_token = OAuthAccessToken(
                application=OAuthApplication(
                    client_id={
                        "desktop_eu": ARRAY_APP_CLIENT_ID_EU,
                        "mobile": POSTHOG_DESKTOP_MOBILE_APP_CLIENT_ID_US,
                    }.get(caller, ARRAY_APP_CLIENT_ID_US)
                ),
                scope="task:write internal_run:read" if caller == "sandbox" else "task:write",
                source_refresh_token_id="00000000-0000-0000-0000-000000000002",
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
        accepted = caller.startswith("desktop") and not resume
        with patch.object(
            tasks_facade,
            "get_task_run_claude_model_access",
            return_value="own-subscription",
        ):
            assert serializer.is_valid() is accepted, serializer.errors
        if not accepted:
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
