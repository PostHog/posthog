import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from paramiko import RSAKey

from products.warehouse_sources.backend.models.ssh_tunnel import SSHTunnel, SSHTunnelConfig


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


def _host_key_line(key_type: str) -> str:
    if key_type == "ssh-rsa":
        key = RSAKey.generate(2048)
        return f"{key.get_name()} {key.get_base64()}"

    public_key = ed25519.Ed25519PrivateKey.generate().public_key()
    return public_key.public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()


@pytest.mark.parametrize("host_key", [None, "", "   \n  "])
def test_blank_host_key_leaves_server_unverified(host_key):
    # A blank host key is valid and must reach the forwarder as None, so the tunnel keeps the prior
    # unverified behavior instead of failing setup for every source that never set the field.
    tunnel = _password_tunnel(host_key=host_key)

    assert tunnel.is_host_key_valid() == (True, "")
    assert tunnel.parse_host_key() is None
    assert tunnel.get_tunnel("host.com", 3306, ssh_host="93.184.216.34").ssh_host_key is None


@pytest.mark.parametrize(
    "host_key,expected",
    [
        ("not a host key", "no ssh host key found"),
        ("@cert-authority *.example.com ssh-rsa AAAAB3NzaC1yc2E=", "not a host key"),
        ("@revoked host.com ssh-rsa AAAAB3NzaC1yc2E=", "not a host key"),
    ],
)
def test_unparseable_host_key_is_rejected(host_key, expected):
    # A CA or revocation marker line carries a key that must never be pinned as the server's own,
    # and both markers read as an ordinary known_hosts line once the marker token is ignored.
    res, error = _password_tunnel(host_key=host_key).is_host_key_valid()

    assert res is False
    assert expected in error.lower()


@pytest.mark.parametrize("on_one_line", [False, True])
def test_multiple_host_keys_are_rejected(on_one_line):
    # A tunnel pins exactly one key, so taking whichever key parses first pins a key the user never
    # chose and ignores the rest without saying so. Counting keys per line misses the one-line case.
    rsa_key, ed25519_key = _host_key_line("ssh-rsa"), _host_key_line("ssh-ed25519")
    if on_one_line:
        paste = f"host.com {rsa_key} {ed25519_key}"
    else:
        paste = "\n".join(["# host.com:22 SSH-2.0-OpenSSH_9.6", f"host.com {rsa_key}", f"host.com {ed25519_key}"])

    res, error = _password_tunnel(host_key=paste).is_host_key_valid()

    assert res is False
    assert "single host key" in error.lower()


def test_a_host_key_wrapped_across_lines_is_rejected():
    # paramiko zero-fills a short blob instead of raising, so a wrapped paste builds a well-formed
    # key that can never match the server. Without this the source saves clean and every later sync
    # fails at the handshake as a host-key mismatch, which reads as an attack rather than a bad paste.
    key_type, key_base64 = _host_key_line("ssh-rsa").split()

    res, error = _password_tunnel(host_key=f"{key_type} {key_base64[:60]}\n{key_base64[60:]}").is_host_key_valid()

    assert res is False
    assert "incomplete" in error.lower()


def test_a_key_advertised_under_an_sha2_name_is_accepted():
    # `rsa-sha2-256` and `rsa-sha2-512` are registered RSA identifiers, so a paste naming either
    # must parse rather than read as "no host key found".
    _, key_base64 = _host_key_line("ssh-rsa").split()

    parsed = _password_tunnel(host_key=f"rsa-sha2-256 {key_base64}").parse_host_key()

    assert parsed is not None
    assert parsed.get_base64() == key_base64


@pytest.mark.parametrize(
    "key_type,hostname",
    [
        ("ssh-rsa", None),
        ("ssh-rsa", "host.com"),
        ("ssh-rsa", "ssh-bastion.example.com"),
        ("ssh-rsa", "ssh-jump.corp.net,10.0.0.5"),
        ("ssh-ed25519", None),
        ("ssh-ed25519", "host.com"),
    ],
)
def test_get_tunnel_pins_host_key(key_type, hostname):
    # A configured host key must reach the forwarder as `ssh_host_key`, or paramiko silently
    # trusts whatever key the server presents. Accept the bare `<type> <base64>` form and a full
    # known_hosts line, including a host field that itself starts with `ssh-`: the parser must not
    # mistake such a host for the algorithm token.
    line = _host_key_line(key_type)
    key_name, key_base64 = line.split()
    tunnel = _password_tunnel(host_key=f"{hostname} {line}" if hostname else line)

    parsed = tunnel.parse_host_key()

    assert parsed is not None
    assert (parsed.get_name(), parsed.get_base64()) == (key_name, key_base64)
    forwarder = tunnel.get_tunnel("host.com", 3306, ssh_host="93.184.216.34")
    assert forwarder.ssh_host_key == parsed


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


def test_config_from_dict_without_an_auth_section():
    ssh_tunnel_config = SSHTunnelConfig.from_dict({"host": "host.com", "port": "22", "enabled": "false"})

    assert ssh_tunnel_config.enabled is False
    assert ssh_tunnel_config.auth.type is None
