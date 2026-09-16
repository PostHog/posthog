import socket

import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from django.test import override_settings

from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.codec import EncryptionCodec

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import HostNotAllowedError
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.temporalio import (
    TemporalIOSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.source import TemporalIOSource
from products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio import (
    _CONTAINER_SIZE_BYTES,
    _SCALAR_SIZE_BYTES,
    FakeSettings,
    _async_iter_to_sync,
    _ByteBudget,
    _estimate_size_bytes,
    _get_temporal_client,
    _with_transient_rpc_retry,
)

_MIXINS_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins"


def _rpc_error(message: str, status: RPCStatusCode) -> RPCError:
    return RPCError(message, status, b"")


def _config(host: str = "temporal.example.com") -> TemporalIOSourceConfig:
    return TemporalIOSourceConfig.from_dict(
        {
            "host": host,
            "port": "7233",
            "namespace": "namespace",
            "server_client_root_ca": "ca",
            "client_certificate": "cert",
            "client_private_key": "key",
        }
    )


def _resolves_to(ip: str) -> list:
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))]


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
            await _get_temporal_client(config, team_id=999)

        data_converter = mock_connect.call_args.kwargs["data_converter"]
        assert isinstance(data_converter.payload_codec, EncryptionCodec)

    @pytest.mark.parametrize("resolved_ip", ["169.254.169.254", "10.0.0.5"])
    async def test_a_host_resolving_to_an_internal_ip_is_refused_before_dialling(self, resolved_ip):
        with (
            override_settings(CLOUD_DEPLOYMENT="US"),
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", return_value=_resolves_to(resolved_ip)),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch.object(Client, "connect", new=AsyncMock(return_value=MagicMock())) as mock_connect,
        ):
            with pytest.raises(HostNotAllowedError):
                await _get_temporal_client(_config(), team_id=999)

        mock_connect.assert_not_called()

    async def test_a_public_host_is_dialled(self):
        with (
            override_settings(CLOUD_DEPLOYMENT="US"),
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", return_value=_resolves_to("93.184.216.34")),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch.object(Client, "connect", new=AsyncMock(return_value=MagicMock())) as mock_connect,
        ):
            await _get_temporal_client(_config(), team_id=999)

        assert mock_connect.call_args.args[0] == "temporal.example.com:7233"

    def test_creating_a_source_on_an_internal_host_is_rejected(self):
        with (
            override_settings(CLOUD_DEPLOYMENT="US"),
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", return_value=_resolves_to("10.0.0.5")),
            patch(f"{_MIXINS_MODULE}.logger"),
        ):
            is_valid, error = TemporalIOSource().validate_credentials(_config(), team_id=999)

        assert not is_valid
        assert error


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
            # A mid-stream HTTP/2 transport interruption surfaces as UNKNOWN, not one of the
            # transient statuses above — it must still be ridden out in-process.
            ("h2 protocol error: error reading a body from connection", RPCStatusCode.UNKNOWN),
            # tonic cancels a call that outruns the client's RPC deadline with status CANCELLED and
            # message "Timeout expired" — a client-side timeout that must be ridden out, not raised.
            ("Timeout expired", RPCStatusCode.CANCELLED),
            # A transport connection closed mid-request also surfaces as CANCELLED, with message
            # "operation was canceled" — a connection blip, not a real cancellation.
            ("operation was canceled", RPCStatusCode.CANCELLED),
            # A DNS resolution blip surfaces as UNAVAILABLE — a connection-level failure that must
            # be ridden out rather than failing the whole import activity.
            ("dns error", RPCStatusCode.UNAVAILABLE),
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
            ("dns error", RPCStatusCode.UNAVAILABLE),
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

    @pytest.mark.parametrize(
        "message,status",
        [
            ("workflow execution not found for", RPCStatusCode.NOT_FOUND),
            # UNKNOWN alone must not be retried — only UNKNOWN carrying a transport signature is.
            ("internal server error", RPCStatusCode.UNKNOWN),
            # CANCELLED alone must not be retried — only the "Timeout expired" and "operation was
            # canceled" phrases qualify.
            ("Cancelled by caller", RPCStatusCode.CANCELLED),
        ],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_non_transient_rpc_error_is_not_retried(self, sleep, message, status):
        async def operation():
            raise _rpc_error(message, status)

        with pytest.raises(RPCError):
            await _with_transient_rpc_retry(operation, MagicMock())

        assert sleep.await_count == 0


class TestEstimateSizeBytes:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("abcd", 4),
            (b"abcd", 4),
            (True, _SCALAR_SIZE_BYTES),
            (None, _SCALAR_SIZE_BYTES),
            (12345, _SCALAR_SIZE_BYTES),
            ({}, _CONTAINER_SIZE_BYTES),
            ([], _CONTAINER_SIZE_BYTES),
            ({"ab": "cdef"}, _CONTAINER_SIZE_BYTES + 2 + 4),
            (["ab", "cd"], _CONTAINER_SIZE_BYTES + 2 + 2),
        ],
    )
    def test_measures_value(self, value, expected):
        assert _estimate_size_bytes(value) == expected

    def test_counts_strings_nested_below_the_top_level(self):
        payload = "x" * 10_000
        nested = {"events": [{"input": {"payload": payload}}]}

        assert _estimate_size_bytes(nested) >= len(payload)


class TestByteBudget:
    @pytest.mark.parametrize(
        "reserve_first,size,expected",
        [
            # An empty budget admits an item larger than the cap. Without this the producer waits on
            # a bound it can never satisfy and the whole sync hangs.
            (0, 5000, True),
            (0, 10, True),
            (40, 60, True),
            (40, 61, False),
        ],
    )
    def test_admits(self, reserve_first, size, expected):
        budget = _ByteBudget(max_bytes=100)
        if reserve_first:
            budget.reserve(reserve_first)

        assert budget._admits(size) is expected

    def test_release_frees_capacity_for_a_blocked_item(self):
        budget = _ByteBudget(max_bytes=100)
        budget.reserve(100)
        assert budget._admits(100) is False

        budget.release(100)

        assert budget.in_flight_bytes == 0
        assert budget._admits(100) is True


class TestAsyncIterToSync:
    @staticmethod
    async def _aiter(items):
        for item in items:
            yield item

    def test_delivers_every_item_in_order(self):
        items = [{"id": index} for index in range(50)]

        assert list(_async_iter_to_sync(self._aiter(items))) == items

    def test_propagates_a_producer_exception_to_the_consumer(self):
        async def failing():
            yield {"id": 1}
            raise RuntimeError("boom")

        stream = _async_iter_to_sync(failing())

        assert next(stream) == {"id": 1}
        with pytest.raises(RuntimeError, match="boom"):
            next(stream)

    def test_reserves_and_releases_stay_balanced(self):
        # Catches both halves of the accounting. A reservation the consumer never releases leaks
        # until the producer blocks on a budget that only fills; an item enqueued without reserving
        # never counts against the cap at all, which is the unbounded behavior this bound replaced.
        budgets = []

        def _record(max_bytes):
            budgets.append(_ByteBudget(max_bytes))
            return budgets[-1]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio._ByteBudget",
            side_effect=_record,
        ):
            # A cap every item fits under, so a missing release surfaces as leftover in-flight bytes
            # rather than a producer that blocks and hangs the test.
            items = [{"payload": "x" * 100} for _ in range(10)]
            assert list(_async_iter_to_sync(self._aiter(items), max_bytes=100_000)) == items

        assert budgets[0].in_flight_bytes == 0
