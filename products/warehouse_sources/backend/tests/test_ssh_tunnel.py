import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from paramiko import RSAKey

from products.warehouse_sources.backend.models.ssh_tunnel import SSHTunnel


def _password_tunnel(host_key: str | None) -> SSHTunnel:
    return SSHTunnel(
        enabled=True,
        host="host.com",
        port=5432,
        auth_type="password",
        username="user1",
        password="password",
        private_key=None,
        passphrase=None,
        host_key=host_key,
    )


def _keypair_tunnel(private_key: str | None, passphrase: str | None) -> SSHTunnel:
    return SSHTunnel(
        enabled=True,
        host="host.com",
        port=5432,
        auth_type="keypair",
        username=None,
        password=None,
        private_key=private_key,
        passphrase=passphrase,
    )


@pytest.mark.parametrize("port,expected", [(5432, True), (80, False), (443, False)])
def test_valid_port(port, expected):
    ssh_tunnel = SSHTunnel(
        enabled=True,
        host="host.com",
        port=port,
        auth_type="password",
        username="user1",
        password="password",
        private_key=None,
        passphrase=None,
    )

    res, error = ssh_tunnel.has_valid_port()

    assert res is expected


@pytest.mark.parametrize(
    "username,password,expected",
    [
        ("User1", "password", True),
        ("", "password", False),
        ("user", "", False),
        ("", "", False),
        ("User", None, False),
        (None, "password", False),
    ],
)
def test_is_auth_valid_password(username, password, expected):
    ssh_tunnel = SSHTunnel(
        enabled=True,
        host="host.com",
        port=5432,
        auth_type="password",
        username=username,
        password=password,
        private_key=None,
        passphrase=None,
    )

    res, error = ssh_tunnel.is_auth_valid()

    assert res is expected


@pytest.mark.parametrize(
    "private_key,passphrase,expected",
    [
        ("Blah", "password", False),
        ("", "password", False),
        (None, "password", False),
        ("Blah", "", False),
        ("Blah", None, False),
    ],
)
def test_is_auth_valid_key_pair(private_key, passphrase, expected):
    ssh_tunnel = SSHTunnel(
        enabled=True,
        host="host.com",
        port=5432,
        auth_type="keypair",
        username=None,
        password=None,
        private_key=private_key,
        passphrase=passphrase,
    )

    res, error = ssh_tunnel.is_auth_valid()

    assert res is expected


def test_is_auth_valid_unparseable_key_suggests_format():
    res, error = _keypair_tunnel(private_key="not a private key", passphrase=None).is_auth_valid()

    assert res is False
    assert "OpenSSH or PEM" in error


def test_is_auth_valid_wrong_passphrase_suggests_passphrase():
    key = ed25519.Ed25519PrivateKey.generate()
    encrypted = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.BestAvailableEncryption(b"correct-passphrase"),
    ).decode()

    res, error = _keypair_tunnel(private_key=encrypted, passphrase="wrong-passphrase").is_auth_valid()

    assert res is False
    assert "passphrase" in error.lower()


def test_blank_host_key_leaves_server_unverified():
    # A blank host key is valid and parses to None, so the forwarder keeps the prior
    # unverified behavior instead of failing setup.
    tunnel = _password_tunnel(host_key=None)

    assert tunnel.is_host_key_valid() == (True, "")
    assert tunnel.parse_host_key() is None


def test_unparseable_host_key_is_rejected():
    res, error = _password_tunnel(host_key="not a host key").is_host_key_valid()

    assert res is False
    assert "host key" in error.lower()


@pytest.mark.parametrize(
    "hostname",
    [None, "host.com", "ssh-bastion.example.com", "ssh-jump.corp.net,10.0.0.5"],
)
def test_get_tunnel_pins_host_key(hostname):
    # A configured host key must reach the forwarder as `ssh_host_key`, or paramiko silently
    # trusts whatever key the server presents. Accept the bare `<type> <base64>` form and a full
    # known_hosts line (raw `ssh-keyscan` output), including a host field that itself starts with
    # `ssh-`: the parser must not mistake such a host for the algorithm token.
    server_key = RSAKey.generate(2048)
    line = f"{server_key.get_name()} {server_key.get_base64()}"
    if hostname:
        line = f"{hostname} {line}"

    tunnel = _password_tunnel(host_key=line)

    assert tunnel.parse_host_key() == server_key
    forwarder = tunnel.get_tunnel("host.com", 3306, ssh_host="93.184.216.34")
    assert forwarder.ssh_host_key == server_key


def test_get_tunnel_invalid_auth():
    ssh_tunnel = SSHTunnel(
        enabled=True,
        host="host.com",
        port=5432,
        auth_type="password",
        username="",
        password="",
        private_key=None,
        passphrase=None,
    )

    with pytest.raises(Exception) as e:
        ssh_tunnel.get_tunnel("host.com", 1337, ssh_host="93.184.216.34")
        assert "auth" in str(e.value)


def test_get_tunnel_invalid_port():
    ssh_tunnel = SSHTunnel(
        enabled=True,
        host="host.com",
        port=80,
        auth_type="password",
        username="user",
        password="password",
        private_key=None,
        passphrase=None,
    )

    with pytest.raises(Exception) as e:
        ssh_tunnel.get_tunnel("host.com", 1337, ssh_host="93.184.216.34")
        assert "port" in str(e.value)
