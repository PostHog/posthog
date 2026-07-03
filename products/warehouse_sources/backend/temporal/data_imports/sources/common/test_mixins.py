from dataclasses import dataclass

import pytest
from unittest import mock
from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    OAuthMixin,
    SSHTunnelMixin,
    ValidateDatabaseHostMixin,
    _is_host_safe,
    make_ssh_tunnel_factory,
    open_ssh_tunnel,
)

_MIXINS_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins"


class TestIsHostSafe(SimpleTestCase):
    @parameterized.expand(
        [
            ("private_10", "10.0.0.1"),
            ("private_172_16", "172.16.0.1"),
            ("private_192_168", "192.168.1.1"),
            ("loopback_127", "127.0.0.1"),
            ("loopback_127_other", "127.0.0.2"),
            ("localhost", "localhost"),
            ("link_local_imds", "169.254.169.254"),
            ("link_local", "169.254.1.1"),
            ("ipv6_mapped_loopback", "::ffff:127.0.0.1"),
            ("ipv6_mapped_imds", "::ffff:169.254.169.254"),
            ("ipv6_mapped_private", "::ffff:10.0.0.1"),
            ("ipv6_loopback", "::1"),
            ("multicast", "224.0.0.1"),
            ("reserved", "0.0.0.0"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_blocks_internal_ip(self, _name: str, host: str):
        valid, error = _is_host_safe(host, team_id=999)
        assert not valid
        assert error is not None

    @parameterized.expand(
        [
            ("public_ip", "8.8.8.8"),
            ("public_ip_2", "1.1.1.1"),
            ("public_ip_3", "52.0.0.1"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allows_public_ip(self, _name: str, host: str):
        valid, _ = _is_host_safe(host, team_id=999)
        assert valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allows_internal_ip_for_whitelisted_team_us(self):
        valid, _ = _is_host_safe("10.0.0.1", team_id=2)
        assert valid

    @override_settings(CLOUD_DEPLOYMENT="EU")
    def test_allows_internal_ip_for_whitelisted_team_eu(self):
        valid, _ = _is_host_safe("10.0.0.1", team_id=1)
        assert valid

    @parameterized.expand(
        [
            ("localhost", "localhost"),
            ("loopback", "127.0.0.1"),
            ("private_ip", "10.0.0.1"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="E2E", E2E_TESTING=True)
    def test_allows_internal_hosts_in_e2e(self, _name: str, host: str):
        valid, error = _is_host_safe(host, team_id=999)
        assert valid
        assert error is None

    @parameterized.expand(
        [
            ("postwh_us", "entirely-chief-wildcat.us.postwh.com"),
            ("postwh_eu", "my-db.eu.postwh.com"),
            ("postwh_bare", "something.postwh.com"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allows_postwh_hosts(self, _name: str, host: str):
        valid, _ = _is_host_safe(host, team_id=999)
        assert valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_blocks_fake_postwh_suffix(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("10.0.0.1", 0))],
        ):
            valid, error = _is_host_safe("evil.postwh.com.evil.example.com", team_id=999)
            assert not valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_dns_resolving_to_internal_ip_blocked(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("10.0.0.1", 0))],
        ):
            valid, error = _is_host_safe("evil.example.com", team_id=999)
            assert not valid
            assert error == "Hosts with internal IP addresses are not allowed"

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_dns_resolving_to_public_ip_allowed(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("52.1.2.3", 0))],
        ):
            valid, _ = _is_host_safe("good.example.com", team_id=999)
            assert valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_unresolvable_host_blocked(self):
        import socket

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.socket.getaddrinfo",
            side_effect=socket.gaierror("Name or service not known"),
        ):
            valid, error = _is_host_safe("nonexistent.invalid", team_id=999)
            assert not valid
            assert error is not None
            assert "nonexistent.invalid" in error
            assert "resolve" in error

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_blocked_host_logs_warning(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.logger"
        ) as mock_logger:
            valid, _ = _is_host_safe("10.0.0.1", team_id=999)
            assert not valid
            mock_logger.warning.assert_called_once()
            _args, kwargs = mock_logger.warning.call_args
            assert kwargs["decision"] == "block"
            assert kwargs["stage"] == "literal_ip"
            assert kwargs["host"] == "10.0.0.1"
            mock_logger.info.assert_not_called()

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allowed_resolved_host_logs_info_with_resolved_ips(self):
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.socket.getaddrinfo",
                return_value=[(None, None, None, None, ("52.1.2.3", 0))],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.logger"
            ) as mock_logger,
        ):
            valid, _ = _is_host_safe("good.example.com", team_id=999)
            assert valid
            mock_logger.info.assert_called_once()
            _args, kwargs = mock_logger.info.call_args
            assert kwargs["decision"] == "allow"
            assert kwargs["stage"] == "resolved_ip"
            assert kwargs["resolved_ips"] == ["52.1.2.3"]
            mock_logger.warning.assert_not_called()


class TestValidateDatabaseHostMixin(SimpleTestCase):
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_blocks_private_ip(self):
        mixin = ValidateDatabaseHostMixin()
        valid, error = mixin.is_database_host_valid("192.168.1.1", team_id=999)
        assert not valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allows_public_ip(self):
        mixin = ValidateDatabaseHostMixin()
        valid, _ = mixin.is_database_host_valid("8.8.8.8", team_id=999)
        assert valid


@dataclass
class FakeSSHTunnelConfig:
    enabled: bool
    host: str
    port: int = 22


@dataclass
class FakeConfig:
    host: str = "dbhost.example.com"
    port: int = 5432
    ssh_tunnel: FakeSSHTunnelConfig | None = None


class TestSSHTunnelHostValidation(SimpleTestCase):
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_ssh_tunnel_with_internal_host_blocked(self):
        mixin = SSHTunnelMixin()
        config = FakeConfig(ssh_tunnel=FakeSSHTunnelConfig(enabled=True, host="10.0.0.1"))
        valid, error = mixin.ssh_tunnel_is_valid(config, team_id=999)
        assert not valid
        assert "SSH tunnel host not allowed" in error  # type: ignore

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_ssh_tunnel_disabled_skips_validation(self):
        mixin = SSHTunnelMixin()
        config = FakeConfig(ssh_tunnel=FakeSSHTunnelConfig(enabled=False, host="10.0.0.1"))
        valid, _ = mixin.ssh_tunnel_is_valid(config, team_id=999)
        assert valid

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_no_ssh_tunnel_skips_validation(self):
        mixin = SSHTunnelMixin()
        config = FakeConfig(ssh_tunnel=None)
        valid, _ = mixin.ssh_tunnel_is_valid(config, team_id=999)
        assert valid

    @parameterized.expand(
        [
            ("imds", "169.254.169.254"),
            ("loopback", "127.0.0.1"),
            ("private_192", "192.168.0.1"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_ssh_tunnel_blocks_various_internal_hosts(self, _name: str, host: str):
        mixin = SSHTunnelMixin()
        config = FakeConfig(ssh_tunnel=FakeSSHTunnelConfig(enabled=True, host=host))
        valid, _ = mixin.ssh_tunnel_is_valid(config, team_id=999)
        assert not valid


class TestConnectionOpenLogging(SimpleTestCase):
    def test_direct_connection_logs_open_event(self):
        config = FakeConfig(ssh_tunnel=FakeSSHTunnelConfig(enabled=False, host=""))
        with patch(f"{_MIXINS_MODULE}.logger") as mock_logger:
            with open_ssh_tunnel(config, team_id=42) as (host, port):
                assert (host, port) == ("dbhost.example.com", 5432)
        mock_logger.info.assert_called_once()
        args, kwargs = mock_logger.info.call_args
        assert args[0] == "data_imports.connection_open"
        assert kwargs["db_host"] == "dbhost.example.com"
        assert kwargs["db_port"] == 5432
        assert kwargs["via"] == "direct"
        assert kwargs["team_id"] == 42
        assert "ssh_host" not in kwargs
        mock_logger.warning.assert_not_called()

    def test_none_team_id_is_omitted_so_contextvars_can_fill_it(self):
        config = FakeConfig(ssh_tunnel=None)
        with patch(f"{_MIXINS_MODULE}.logger") as mock_logger:
            with open_ssh_tunnel(config):
                pass
        _args, kwargs = mock_logger.info.call_args
        assert "team_id" not in kwargs

    def test_tunneled_connection_logs_both_hosts(self):
        config = FakeConfig(ssh_tunnel=FakeSSHTunnelConfig(enabled=True, host="0.tcp.ngrok.example", port=12345))
        with (
            patch(f"{_MIXINS_MODULE}.SSHTunnel") as mock_ssh,
            patch(f"{_MIXINS_MODULE}.logger") as mock_logger,
        ):
            tunnel = mock_ssh.from_config.return_value.get_tunnel.return_value.__enter__.return_value
            tunnel.local_bind_host, tunnel.local_bind_port = "127.0.0.1", 55555
            with open_ssh_tunnel(config, team_id=42) as (host, port):
                assert (host, port) == ("127.0.0.1", 55555)
        _args, kwargs = mock_logger.info.call_args
        assert kwargs["via"] == "ssh_tunnel"
        assert kwargs["ssh_host"] == "0.tcp.ngrok.example"
        assert kwargs["ssh_port"] == 12345
        assert kwargs["db_host"] == "dbhost.example.com"

    def test_error_inside_connection_block_logs_connection_error(self):
        config = FakeConfig(ssh_tunnel=None)
        with patch(f"{_MIXINS_MODULE}.logger") as mock_logger:
            with pytest.raises(ConnectionRefusedError):
                with open_ssh_tunnel(config, team_id=42):
                    raise ConnectionRefusedError("connection refused")
        mock_logger.warning.assert_called_once()
        args, kwargs = mock_logger.warning.call_args
        assert args[0] == "data_imports.connection_error"
        assert kwargs["error_type"] == "ConnectionRefusedError"
        assert kwargs["team_id"] == 42

    def test_factory_logs_once_per_reopen(self):
        config = FakeConfig(ssh_tunnel=None)
        factory = make_ssh_tunnel_factory(config, team_id=42)
        with patch(f"{_MIXINS_MODULE}.logger") as mock_logger:
            with factory() as (host, port):
                assert (host, port) == ("dbhost.example.com", 5432)
            with factory():
                pass
        assert mock_logger.info.call_count == 2
        assert all(call.args[0] == "data_imports.connection_open" for call in mock_logger.info.call_args_list)
        # The closure must carry team_id into every reopen — this is the sync-path attribution.
        assert all(call.kwargs["team_id"] == 42 for call in mock_logger.info.call_args_list)


class TestOAuthMixinIntegrationFetchResilience(SimpleTestCase):
    @parameterized.expand(
        [
            ("pool_wait_timeout", "query_wait_timeout"),
            ("dropped_connection", "server closed the connection unexpectedly"),
        ]
    )
    def test_retries_transient_db_error_then_succeeds(self, _name: str, message: str):
        integration = object()
        get = mock.Mock(side_effect=[OperationalError(message), OperationalError(message), integration])

        with (
            patch(f"{_MIXINS_MODULE}.Integration.objects.get", get),
            patch(f"{_MIXINS_MODULE}.close_old_connections") as close,
            patch(f"{_MIXINS_MODULE}.time.sleep") as sleep,
        ):
            result = OAuthMixin().get_oauth_integration(integration_id=1, team_id=2)

        assert result is integration
        assert get.call_count == 3
        # The poisoned connection is evicted before each retry, but not on the successful attempt.
        assert close.call_count == 2
        # Backoff grows per `min(2 * attempt, 30)`: 2s after the 1st failure, 4s after the 2nd.
        assert sleep.call_args_list == [mock.call(2), mock.call(4)]

    def test_success_does_not_evict_connection(self):
        # Closing the connection on the happy path would tear down the caller's open transaction
        # (e.g. inside a transactional test), so eviction must only happen between retries.
        integration = object()

        with (
            patch(f"{_MIXINS_MODULE}.Integration.objects.get", return_value=integration),
            patch(f"{_MIXINS_MODULE}.close_old_connections") as close,
            patch(f"{_MIXINS_MODULE}.time.sleep") as sleep,
        ):
            result = OAuthMixin().get_oauth_integration(integration_id=1, team_id=2)

        assert result is integration
        close.assert_not_called()
        sleep.assert_not_called()

    def test_reraises_after_exhausting_attempts(self):
        get = mock.Mock(side_effect=OperationalError("query_wait_timeout"))

        with (
            patch(f"{_MIXINS_MODULE}.Integration.objects.get", get),
            patch(f"{_MIXINS_MODULE}.close_old_connections"),
            patch(f"{_MIXINS_MODULE}.time.sleep") as sleep,
        ):
            with pytest.raises(OperationalError):
                OAuthMixin().get_oauth_integration(integration_id=1, team_id=2)

        # Bounded attempts: it gives up rather than looping forever, leaving Temporal to retry the activity.
        assert get.call_count == 4
        # Backed off between attempts (2s, 4s, 6s) but not after the final attempt that re-raises.
        assert sleep.call_args_list == [mock.call(2), mock.call(4), mock.call(6)]

    def test_missing_integration_is_not_retried(self):
        get = mock.Mock(side_effect=Integration.DoesNotExist())

        with (
            patch(f"{_MIXINS_MODULE}.Integration.objects.get", get),
            patch(f"{_MIXINS_MODULE}.close_old_connections"),
            patch(f"{_MIXINS_MODULE}.time.sleep") as sleep,
        ):
            # A deleted integration is non-retryable — surfaced as the stable "Integration not found"
            # message the sources classify as non-retryable, not masked as a transient drop.
            with pytest.raises(ValueError, match="Integration not found"):
                OAuthMixin().get_oauth_integration(integration_id=1, team_id=2)

        assert get.call_count == 1
        sleep.assert_not_called()

    def test_deletion_during_retry_is_surfaced_as_not_found(self):
        # The row vanishes after a transient failure: the retry must convert DoesNotExist into the
        # stable non-retryable ValueError rather than letting raw DoesNotExist escape and be retried.
        get = mock.Mock(side_effect=[OperationalError("query_wait_timeout"), Integration.DoesNotExist()])

        with (
            patch(f"{_MIXINS_MODULE}.Integration.objects.get", get),
            patch(f"{_MIXINS_MODULE}.close_old_connections"),
            patch(f"{_MIXINS_MODULE}.time.sleep"),
        ):
            with pytest.raises(ValueError, match="Integration not found"):
                OAuthMixin().get_oauth_integration(integration_id=1, team_id=2)

        assert get.call_count == 2
