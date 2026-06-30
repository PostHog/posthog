import pytest
from unittest import mock

from sshtunnel import BaseSSHTunnelForwarderError

from products.warehouse_sources.backend.models.ssh_tunnel import SSHTunnel, _DetailCapturingForwarder


def _tunnel() -> SSHTunnel:
    return SSHTunnel(
        enabled=True,
        host="bastion.example.com",
        port=22,
        auth_type="password",
        username="user",
        password="pass",
        private_key=None,
        passphrase=None,
    )


def test_get_tunnel_surfaces_underlying_reason():
    # sshtunnel logs the specific failure (here, a refused gateway connection) and then raises a
    # generic "Could not establish session to SSH gateway". The forwarder must fold the logged
    # reason back into the exception so the connection test shows the customer something to debug.
    forwarder = _tunnel().get_tunnel("db.internal", 5432)
    assert isinstance(forwarder, _DetailCapturingForwarder)

    def fake_start(self):
        self.logger.error("Could not connect to gateway bastion.example.com:22 : [Errno 111] Connection refused")
        raise BaseSSHTunnelForwarderError(value="Could not establish session to SSH gateway")

    with mock.patch("sshtunnel.SSHTunnelForwarder.start", fake_start):
        with pytest.raises(BaseSSHTunnelForwarderError) as exc:
            forwarder.start()

    message = str(exc.value.value)
    assert "Could not establish session to SSH gateway" in message
    assert "[Errno 111] Connection refused" in message


def test_get_tunnel_passthrough_when_no_detail_captured():
    # If nothing specific was logged, don't fabricate detail — re-raise the original generic error.
    forwarder = _tunnel().get_tunnel("db.internal", 5432)

    def fake_start(self):
        raise BaseSSHTunnelForwarderError(value="Could not establish session to SSH gateway")

    with mock.patch("sshtunnel.SSHTunnelForwarder.start", fake_start):
        with pytest.raises(BaseSSHTunnelForwarderError) as exc:
            forwarder.start()

    assert str(exc.value.value) == "Could not establish session to SSH gateway"
