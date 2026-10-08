import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from django.test import override_settings

from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.codec import EncryptionCodec

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import HostNotAllowedError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.tests.resolver import addrinfo, resolver
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.temporalio import (
    TemporalIOSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.source import TemporalIOSource
from products.warehouse_sources.backend.temporal.data_imports.sources.temporalio.temporalio import (
    FakeSettings,
    TemporalIOResumeConfig,
    _async_iter_to_sync,
    _ByteBudget,
    _estimate_size_bytes,
    _get_temporal_client,
    _ResumePoint,
    _with_transient_rpc_retry,
)

_MIXINS_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins"


def _rpc_error(message: str, status: RPCStatusCode) -> RPCError:
    return RPCError(message, status, b"")


def _payload(**overrides: str) -> dict[str, str]:
    return {
        "host": "temporal.example.com",
        "port": "7233",
        "namespace": "namespace",
        "server_client_root_ca": "ca",
        "client_certificate": "cert",
        "client_private_key": "key",
        **overrides,
    }


def _config(**overrides: str) -> TemporalIOSourceConfig:
    return TemporalIOSourceConfig.from_dict(_payload(**overrides))


class TestTemporalIOClient:
    def test_fake_settings_satisfies_encryption_codec_contract(self):
        # FakeSettings must expose every attribute EncryptionCodec.from_settings reads
        # (TEST, DEBUG, TEMPORAL_SECRET_KEY, TEMPORAL_FALLBACK_SECRET_KEYS); a missing one raises
        # AttributeError. The 32-byte key clears the prod (TEST=False) length guard.
        codec = EncryptionCodec.from_settings(FakeSettings(TEMPORAL_SECRET_KEY="k" * 32))

        assert isinstance(codec, EncryptionCodec)

    async def test_get_temporal_client_builds_encryption_codec(self):
        config = _config(encryption_key="k" * 32)

        with patch.object(Client, "connect", new=AsyncMock(return_value=MagicMock())) as mock_connect:
            await _get_temporal_client(config, team_id=999)

        data_converter = mock_connect.call_args.kwargs["data_converter"]
        assert isinstance(data_converter.payload_codec, EncryptionCodec)

    @pytest.mark.parametrize("resolved_ip", ["169.254.169.254", "10.0.0.5"])
    async def test_a_host_resolving_to_an_internal_ip_is_refused_before_dialling(self, resolved_ip):
        with (
            override_settings(CLOUD_DEPLOYMENT="US"),
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", return_value=addrinfo(0, resolved_ip)),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch.object(Client, "connect", new=AsyncMock(return_value=MagicMock())) as mock_connect,
        ):
            with pytest.raises(HostNotAllowedError):
                await _get_temporal_client(_config(), team_id=999)

        mock_connect.assert_not_called()

    @pytest.mark.parametrize(
        "host,resolved,expected_target,expected_tls_domain",
        [
            ("temporal.example.com", "93.184.216.34", "93.184.216.34:7233", "temporal.example.com"),
            ("93.184.216.34", "93.184.216.34", "93.184.216.34:7233", None),
            ("2606:4700:4700::1111", "2606:4700:4700::1111", "[2606:4700:4700::1111]:7233", None),
            ("[2606:4700:4700::1111]", "2606:4700:4700::1111", "[2606:4700:4700::1111]:7233", None),
            ("2606:4700:4700:0::1111", "2606:4700:4700::1111", "[2606:4700:4700::1111]:7233", None),
        ],
    )
    async def test_the_checked_address_is_dialled_and_only_a_name_carries_tls(
        self, host, resolved, expected_target, expected_tls_domain
    ):
        # An address has no name of its own for the certificate, however it is written.
        with (
            override_settings(CLOUD_DEPLOYMENT="US"),
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", side_effect=resolver(resolved)),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch.object(Client, "connect", new=AsyncMock(return_value=MagicMock())) as mock_connect,
        ):
            await _get_temporal_client(_config(host=host), team_id=999)

        assert mock_connect.call_args.args[0] == expected_target
        assert mock_connect.call_args.kwargs["tls"].domain == expected_tls_domain

    @pytest.mark.parametrize("port", ["7233@169.254.169.254:80", "not-a-port"])
    def test_a_port_that_is_not_a_number_is_rejected(self, port):
        # `connect()` builds the dial target from host and port, so a port that carries anything
        # but a number moves the target past the host check.
        is_valid, errors = TemporalIOSource().validate_config(_payload(port=port))

        assert not is_valid
        assert errors

    @pytest.mark.parametrize(
        "host,resolved,expected_valid",
        [
            ("temporal.example.com", "10.0.0.5", False),
            ("[2606:4700:4700::1111]", "2606:4700:4700::1111", True),
        ],
    )
    def test_creating_a_source_checks_the_host(self, host, resolved, expected_valid):
        with (
            override_settings(CLOUD_DEPLOYMENT="US"),
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", side_effect=resolver(resolved)),
            patch(f"{_MIXINS_MODULE}.logger"),
        ):
            is_valid, error = TemporalIOSource().validate_credentials(_config(host=host), team_id=999)

        assert is_valid is expected_valid
        assert (error is None) is expected_valid


class TestTransientRPCRetry:
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
    def test_counts_strings_nested_below_the_top_level(self):
        payload = "x" * 10_000
        nested = {"events": [{"input": {"payload": payload}}]}

        assert _estimate_size_bytes(nested) >= len(payload)


class TestByteBudget:
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

    def test_resume_points_are_charged_by_their_page_token_size(self):
        reserved: list[int] = []
        original_reserve = _ByteBudget.reserve

        def _spy(budget, size):
            reserved.append(size)
            original_reserve(budget, size)

        token = "t" * 1000
        saved: list[TemporalIOResumeConfig] = []
        items = [_ResumePoint(state=TemporalIOResumeConfig(next_page_token=token)), {"id": 1}]
        with patch.object(_ByteBudget, "reserve", _spy):
            assert list(_async_iter_to_sync(self._aiter(items), save_resume_state=saved.append)) == [{"id": 1}]

        assert reserved[0] == len(token)
        assert [state.next_page_token for state in saved] == [token]
