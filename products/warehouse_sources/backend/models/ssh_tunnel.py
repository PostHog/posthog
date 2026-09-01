import base64
import typing
import dataclasses
from io import StringIO
from typing import IO, Literal

from cryptography.hazmat.primitives import serialization as crypto_serialization
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed25519, rsa
from paramiko import DSSKey, ECDSAKey, Ed25519Key, PKey, RSAKey
from sshtunnel import SSHTunnelForwarder

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common import config

# Substrings that mark a private-key parse failure as a wrong/missing passphrase rather than a
# format problem, so both the parser and the validator give the same passphrase-specific guidance.
_PASSPHRASE_ERROR_TERMS = ("checksum", "decrypt", "password", "passphrase")

# Prefixes of the SSH public-key algorithm names paramiko can build a host key from. A pasted host
# key may be a bare `<type> <base64>` public key, a full known_hosts line (`<host> <type> <base64>`),
# or raw `ssh-keyscan` output — so we locate the algorithm token rather than assume its position.
_SSH_KEY_TYPE_PREFIXES = ("ssh-", "ecdsa-", "sk-ssh-", "sk-ecdsa-")


def host_key_from_string(value: str) -> PKey:
    """Parse a pasted SSH host public key into a paramiko `PKey`.

    Accepts a bare `<type> <base64>` public key, a `known_hosts` line, or raw `ssh-keyscan`
    output (all three carry the algorithm token followed by the base64 key). The returned key is
    what paramiko compares the server's presented host key against, so a mismatch fails the
    handshake instead of trusting whatever key the server offers.
    """
    tokens = value.split()
    for index, token in enumerate(tokens):
        if not token.startswith(_SSH_KEY_TYPE_PREFIXES) or index + 1 >= len(tokens):
            continue
        # A known_hosts host field can itself start with `ssh-`/`ecdsa-` (e.g. a bastion named
        # `ssh-jump`), so a prefix match is only a candidate. The real algorithm token is the one
        # whose next field is the base64 key, so skip a candidate whose successor is not base64
        # and keep scanning instead of failing on the hostname.
        try:
            key_bytes = base64.b64decode(tokens[index + 1], validate=True)
        except ValueError:
            continue
        return PKey.from_type_string(token, key_bytes)
    raise ValueError("No SSH host key found")


# Taken from https://stackoverflow.com/questions/60660919/paramiko-ssh-client-is-unable-to-unpack-ed25519-key
def from_private_key(file_obj: IO[str], passphrase: str | None = None) -> PKey:
    private_key: PKey | None = None
    file_bytes = bytes(file_obj.read(), "utf-8")
    password = bytes(StringIO(passphrase).read(), "utf-8")
    try:
        key = crypto_serialization.load_ssh_private_key(
            file_bytes,
            password=password,
        )
        file_obj.seek(0)
    except ValueError as ssh_error:
        # A wrong passphrase on an OpenSSH key surfaces as a checksum/decrypt failure. Falling
        # through to the PEM loader masks it with a misleading "no BEGIN/END" error, so re-raise
        # the original — the caller uses it to point the user at the passphrase.
        if any(term in str(ssh_error).lower() for term in _PASSPHRASE_ERROR_TERMS):
            raise
        key = crypto_serialization.load_pem_private_key(  # type: ignore
            file_bytes,
            password=password if passphrase is not None else None,
        )
        encryption_algorithm: crypto_serialization.KeySerializationEncryption
        if passphrase:
            encryption_algorithm = crypto_serialization.BestAvailableEncryption(password)
        else:
            encryption_algorithm = crypto_serialization.NoEncryption()
        file_obj = StringIO(
            key.private_bytes(
                crypto_serialization.Encoding.PEM,
                crypto_serialization.PrivateFormat.OpenSSH,
                encryption_algorithm,
            ).decode("utf-8")
        )
    if isinstance(key, rsa.RSAPrivateKey):
        private_key = RSAKey.from_private_key(file_obj, passphrase)
    elif isinstance(key, ed25519.Ed25519PrivateKey):
        private_key = Ed25519Key.from_private_key(file_obj, passphrase)
    elif isinstance(key, ec.EllipticCurvePrivateKey):
        private_key = ECDSAKey.from_private_key(file_obj, passphrase)
    elif isinstance(key, dsa.DSAPrivateKey):
        private_key = DSSKey.from_private_key(file_obj, passphrase)
    else:
        raise TypeError

    return private_key


@config.config
class SSHTunnelAuthConfig(config.Config):
    """Configuration for SSH tunnel authentication."""

    type: Literal["password", "keypair"] | None = config.value(alias="selection")
    password: str | None = None
    passphrase: str | None = None
    private_key: str | None = None
    username: str | None = None


@config.config
class SSHTunnelRequireTlsConfig(config.Config):
    enabled: bool = config.value(converter=config.str_to_bool, default=True)


@config.config
class SSHTunnelConfig(config.Config):
    host: str | None
    port: int | None = config.value(converter=config.str_to_optional_int)
    auth: SSHTunnelAuthConfig = config.value(alias="auth_type", default_factory=SSHTunnelAuthConfig)
    enabled: bool = config.value(converter=config.str_to_bool, default=False)
    require_tls: SSHTunnelRequireTlsConfig = config.value(default_factory=SSHTunnelRequireTlsConfig)
    # Optional pinned host key for the SSH server. When set, paramiko verifies the server presents
    # this exact key and rejects any other. Left blank keeps the prior behavior: the tunnel is
    # encrypted but the server's identity is not checked.
    host_key: str | None = None


@frozen
class SSHTunnel:
    enabled: bool

    host: str
    port: int | str
    auth_type: Literal["password", "keypair"]
    username: str | None
    password: str | None = dataclasses.field(repr=False)
    private_key: str | None = dataclasses.field(repr=False)
    passphrase: str | None = dataclasses.field(repr=False)
    # Public host key, so safe to keep in repr; None means the server's identity is not verified.
    host_key: str | None = None

    @classmethod
    def from_config(cls: type[typing.Self], config: SSHTunnelConfig) -> typing.Self:
        # We should not be calling this if SSH tunneling is not enabled.
        # Currently, we don't: The function is always guarded by an if check.
        # However, this is not reliable: Anybody can forget the if and introduce
        # a bug.
        # TODO: Refactor this so that we don't need these assertions nor can we
        # fail if somebody forgets an if check.
        assert config.host
        assert config.port
        assert config.auth.type

        return cls(
            enabled=config.enabled,
            host=config.host,
            port=config.port,
            auth_type=config.auth.type,
            username=config.auth.username,
            password=config.auth.password,
            private_key=config.auth.private_key,
            passphrase=config.auth.passphrase,
            host_key=config.host_key or None,
        )

    def parse_private_key(self) -> PKey:
        if self.passphrase is None:
            passphrase = None
        elif len(self.passphrase) == 0:
            passphrase = None
        else:
            passphrase = self.passphrase

        return from_private_key(StringIO(self.private_key), passphrase)

    def parse_host_key(self) -> PKey | None:
        """Return the pinned host key as a paramiko `PKey`, or None when none is configured."""
        if self.host_key is None or len(self.host_key.strip()) == 0:
            return None
        return host_key_from_string(self.host_key)

    def is_host_key_valid(self) -> tuple[bool, str]:
        # The host key is optional, so a blank value is valid and just leaves the server unverified.
        if self.host_key is None or len(self.host_key.strip()) == 0:
            return True, ""

        try:
            self.parse_host_key()
        except Exception:
            return False, (
                "SSH host key could not be parsed. Paste the server's public host key as "
                "`<type> <base64>` (for example the output of `ssh-keyscan -p <port> <host>`), or leave it "
                "blank to skip host verification."
            )

        return True, ""

    def is_auth_valid(self) -> tuple[bool, str]:
        if self.auth_type != "password" and self.auth_type != "keypair":
            return False, "Authentication type not recognised"  # type: ignore

        if self.auth_type == "password":
            valid_username = self.username is not None and len(self.username) > 0
            valid_password = self.password is not None and len(self.password) > 0

            return valid_username and valid_password, "Username and password required"

        if self.auth_type == "keypair":
            valid_private_key = self.private_key is not None and len(self.private_key) > 0
            if not valid_private_key:
                return False, "Private key is required"

            try:
                self.parse_private_key()
            except Exception as e:
                # A wrong/missing passphrase and an unsupported key format both land here but need
                # different fixes, so point the user at the likely cause. cryptography's message
                # mentions the password/checksum only for passphrase mismatches.
                detail = str(e).lower()
                if any(term in detail for term in _PASSPHRASE_ERROR_TERMS):
                    return False, (
                        "Private key could not be parsed. Check the passphrase: an encrypted key needs the "
                        "correct passphrase, and an unencrypted key needs the passphrase field left blank."
                    )
                return False, (
                    "Private key could not be parsed. Paste the full key in OpenSSH or PEM format "
                    "(RSA, Ed25519, ECDSA, or DSA), including the BEGIN and END lines."
                )

            return True, ""

        return False, ""  # type: ignore

    def has_valid_port(self) -> tuple[bool, str]:
        try:
            port = int(self.port)
        except (TypeError, ValueError):
            return False, "Port must be a number between 1 and 65535"

        # Out-of-range ports otherwise slip through to sshtunnel, which asserts `0 <= port <= 65535`
        # and raises a bare AssertionError ("PORT < 0 (...)") that surfaces as error-tracking noise.
        if port < 1 or port > 65535:
            return False, "Port must be between 1 and 65535"

        if port == 80 or port == 443:
            return False, f"Port {port} is not allowed"

        return True, ""

    def get_tunnel(self, remote_host: str, remote_port: int, *, ssh_host: str) -> SSHTunnelForwarder:
        """Open a forwarder to `ssh_host`, which is the address `self.host` resolved to.

        `ssh_host` is required rather than defaulted to `self.host` so that a caller cannot
        skip the SSRF check by omitting it: see `resolve_safe_host` for why the checked address
        and the connected address have to be the same one. Passing an IP does not weaken host-key
        verification: paramiko compares the pinned `ssh_host_key` against the key the server
        presents, not against the name we dialed.
        """
        if not self.is_auth_valid()[0]:
            raise Exception("SSHTunnel auth is not valid")

        if not self.has_valid_port()[0]:
            raise Exception("SSHTunnel port is not valid")

        if not self.is_host_key_valid()[0]:
            raise Exception("SSHTunnel host key is not valid")

        # None leaves the handshake unverified, exactly as before this field existed.
        ssh_host_key = self.parse_host_key()

        if self.auth_type == "password":
            return SSHTunnelForwarder(
                (ssh_host, int(self.port)),
                ssh_username=self.username,
                ssh_password=self.password,
                ssh_host_key=ssh_host_key,
                remote_bind_address=(remote_host, remote_port),
                local_bind_address=("127.0.0.1",),
            )
        else:
            return SSHTunnelForwarder(
                (ssh_host, int(self.port)),
                ssh_username=self.username,
                ssh_pkey=self.parse_private_key(),
                ssh_private_key_password=self.passphrase,
                ssh_host_key=ssh_host_key,
                remote_bind_address=(remote_host, remote_port),
                local_bind_address=("127.0.0.1",),
            )
