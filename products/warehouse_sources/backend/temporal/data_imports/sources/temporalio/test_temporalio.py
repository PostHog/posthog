import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.codec import EncryptionCodec

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TemporalIOSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.source import TemporalIOSource
from products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio import (
    FakeSettings,
    _get_temporal_client,
    _with_transient_rpc_retry,
)


def _rpc_error(message: str, status: RPCStatusCode) -> RPCError:
    return RPCError(message, status, b"")


class TestTemporalIOClient:
    def test_fake_settings_satisfies_encryption_codec_contract(self):
        # FakeSettings must expose every attribute EncryptionCodec.from_settings reads
        # (TEST, DEBUG, TEMPORAL_SECRET_KEY, TEMPORAL_FALLBACK_SECRET_KEYS); a missing one raises
        # AttributeError. The 32-byte key clears the prod (TEST=False) length guard.
        codec = EncryptionCodec.from_settings(FakeSettings(TEMPORAL_SECRET_KEY="k" * 32))

        assert isinstance(codec, EncryptionCodec)

    async def test_get_temporal_client_builds_encryption_codec(self):
        config = TemporalIOSourceConfig.from_dict(
            {
                "host": "host",
                "port": "7233",
                "namespace": "namespace",
                "encryption_key": "k" * 32,
                "server_client_root_ca": "ca",
                "client_certificate": "cert",
                "client_private_key": "key",
            }
        )

        with patch.object(Client, "connect", new=AsyncMock(return_value=MagicMock())) as mock_connect:
            await _get_temporal_client(config)

        data_converter = mock_connect.call_args.kwargs["data_converter"]
        assert isinstance(data_converter.payload_codec, EncryptionCodec)


class TestTemporalIONonRetryableErrors:
    def setup_method(self):
        self.source = TemporalIOSource()

    @pytest.mark.parametrize(
        "error_message",
        [
            'RuntimeError: Failed client connect: `get_system_info` call error after connection: Status { code: Unknown, message: "transport error", source: Some(tonic::transport::Error(Transport, hyper::Error(Io, Custom { kind: InvalidData, error: "received fatal alert: UnknownCA" }))) }',
            "received fatal alert: CertificateExpired",
            "received fatal alert: CertificateRevoked",
            "received fatal alert: BadCertificate",
            "received fatal alert: CertificateUnknown",
            "invalid peer certificate: UnknownIssuer",
            "Failed client connect: Server connection error: tonic::transport::Error(Transport, CertificateParseError)",
            'RuntimeError: Failed client connect: invalid target URL: empty host: ":7233"',
            "tonic::transport::Error(Transport, InvalidUri(InvalidUri(InvalidFormat))): invalid target URL: empty host",
            'RuntimeError: Failed client connect: Server connection error: tonic::transport::Error(Transport, ConnectError(ConnectError("dns error", Custom { kind: Uncategorized, error: "failed to lookup address information: Name or service not known" })))',
        ],
    )
    def test_config_failures_are_non_retryable(self, error_message):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert any(pattern in error_message for pattern in non_retryable_errors), (
            f"Expected '{error_message}' to match a non-retryable pattern"
        )

    @pytest.mark.parametrize(
        "error_message",
        [
            'RuntimeError: Failed client connect: `get_system_info` call error after connection: Status { code: Unauthenticated, message: "Jwt is missing", metadata: MetadataMap { headers: {"www-authenticate": "Bearer realm=\\"https://us-east4.gcp.api.temporal.io/temporal.api.workflowservice.v1.WorkflowService/GetSystemInfo\\"", "content-type": "application/grpc", "server": "temporal"} }, source: None }',
        ],
    )
    def test_authentication_failures_are_non_retryable(self, error_message):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert any(pattern in error_message for pattern in non_retryable_errors), (
            f"Expected '{error_message}' to match a non-retryable pattern"
        )

    @pytest.mark.parametrize(
        "error_message",
        [
            "activity Heartbeat timeout",
            'RuntimeError: Failed client connect: `get_system_info` call error after connection: Status { code: Unknown, message: "transport error", source: Some(tonic::transport::Error(Transport, hyper::Error(Io, Os { code: 60, kind: TimedOut, message: "Operation timed out" }))) }',
            # EAI_AGAIN is a transient resolver failure, distinct from the EAI_NONAME phrase we treat
            # as non-retryable — it must keep retrying.
            'RuntimeError: Failed client connect: Server connection error: tonic::transport::Error(Transport, ConnectError(ConnectError("dns error", Custom { kind: Uncategorized, error: "failed to lookup address information: Temporary failure in name resolution" })))',
        ],
    )
    def test_transient_failures_stay_retryable(self, error_message):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert not any(pattern in error_message for pattern in non_retryable_errors), (
            f"'{error_message}' must not match a non-retryable pattern"
        )


class TestTransientRPCRetry:
    @pytest.mark.parametrize(
        "message,status",
        [
            ("namespace rate limit exceeded", RPCStatusCode.RESOURCE_EXHAUSTED),
            ("downstream duration timeout", RPCStatusCode.DEADLINE_EXCEEDED),
        ],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_rides_out_transient_error(self, sleep, message, status):
        calls = {"n": 0}

        async def operation():
            calls["n"] += 1
            if calls["n"] <= 2:
                raise _rpc_error(message, status)
            return "ok"

        result = await _with_transient_rpc_retry(operation, MagicMock())

        assert result == "ok"
        assert calls["n"] == 3
        # Backoff grows per attempt per `min(2 * attempt, 30)`: 2s after the 1st failure, 4s after the 2nd.
        assert sleep.await_args_list == [call(2), call(4)]

    @pytest.mark.parametrize(
        "message,status",
        [
            ("namespace rate limit exceeded", RPCStatusCode.RESOURCE_EXHAUSTED),
            ("downstream duration timeout", RPCStatusCode.DEADLINE_EXCEEDED),
        ],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_persistent_transient_error_is_reraised(self, sleep, message, status):
        async def operation():
            raise _rpc_error(message, status)

        with pytest.raises(RPCError):
            await _with_transient_rpc_retry(operation, MagicMock(), max_attempts=4)

        # Bounded attempts leave Temporal to retry; backs off between attempts but not after the last.
        assert sleep.await_args_list == [call(2), call(4), call(6)]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_non_transient_rpc_error_is_not_retried(self, sleep):
        async def operation():
            raise _rpc_error("workflow execution not found for", RPCStatusCode.NOT_FOUND)

        with pytest.raises(RPCError):
            await _with_transient_rpc_retry(operation, MagicMock())

        assert sleep.await_count == 0
