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

# The algorithm names paramiko can build a host key from. These are the classes `from_type_string`
# dispatches on, so each name it accepts is listed here and no other. A pasted host key may be a
# bare `<type> <base64>` public key or a full known_hosts line (`<host> <type> <base64>`), so we
# match the algorithm token rather than assume its position. Certificates are excluded, because a
# certificate is not a host key.
_SSH_KEY_TYPES = frozenset(
    identifier
    for key_class in (DSSKey, RSAKey, Ed25519Key, ECDSAKey)
    for identifier in key_class.identifiers()
    if "-cert-v01@" not in identifier
)

_HOST_KEY_FORMAT_HELP = (
    "Paste the server's public host key as `<type> <base64>`, for example one line of "
    "`ssh-keyscan -p <port> <host>` output, or leave it blank to connect without verifying the server."
)


class HostKeyParseError(ValueError):
    """Carries the user-facing reason a pasted host key was rejected."""


def _host_keys_from_line(line: str) -> list[PKey]:
    """Return every host key on one known_hosts-style line."""
    keys: list[PKey] = []
    tokens = line.split()
    for index, token in enumerate(tokens):
        if token not in _SSH_KEY_TYPES or index + 1 >= len(tokens):
            continue
        try:
            key_bytes = base64.b64decode(tokens[index + 1], validate=True)
            key = PKey.from_type_string(token, key_bytes)
        except Exception:
            continue
        # paramiko zero-fills a short blob instead of raising, so a key whose base64 wrapped across
        # lines still builds a well-formed key that can never match the server. Only a key that
        # re-serializes to exactly the bytes pasted is the one the user meant to pin.
        if key.asbytes() != key_bytes:
            raise HostKeyParseError(
                "The host key looks incomplete. Paste the whole key on one line, because a line "
                "break inside the key data cuts it short."
            )
        keys.append(key)
    return keys


def host_key_from_string(value: str) -> PKey:
    """Parse one pasted SSH host public key into a paramiko `PKey`.

    Accepts a bare `<type> <base64>` public key or a `known_hosts` line. The returned key is what
    paramiko compares the server's presented host key against, so a mismatch fails the handshake
    instead of trusting whatever key the server offers.

    Rejects a paste that carries more than one key. A tunnel pins exactly one key, so picking one
    of several would verify a server the user did not choose and silently ignore the rest.
    """
    keys: list[PKey] = []
    for line in value.splitlines():
        stripped = line.strip()
        # `ssh-keyscan` interleaves `# host:22 SSH-2.0-...` banner lines with the keys.
        if len(stripped) == 0 or stripped.startswith("#"):
            continue
        if stripped.startswith("@"):
            raise HostKeyParseError(
                "A `@cert-authority` or `@revoked` known_hosts line is not a host key. Paste the "
                "server's own public host key instead."
            )
        keys.extend(_host_keys_from_line(stripped))

    if len(keys) > 1:
        raise HostKeyParseError(
            "Paste a single host key. `ssh-keyscan` prints one line per key type, so pick the one "
            "you want to pin, for example the `ssh-ed25519` line."
        )
    if len(keys) == 0:
        raise HostKeyParseError(f"No SSH host key found. {_HOST_KEY_FORMAT_HELP}")
    return keys[0]


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

    # `SSHTunnelConfig.auth` falls back to an empty auth config, so every field here needs a
    # default. `config.value` ignores `default=None`, so the factory is the way to express it.
    type: Literal["password", "keypair"] | None = config.value(alias="selection", default_factory=lambda: None)
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
        except HostKeyParseError as e:
            return False, str(e)
        except Exception:
            return False, f"SSH host key could not be parsed. {_HOST_KEY_FORMAT_HELP}"

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

        # Parsed once rather than through `is_host_key_valid`, which would parse the same key and
        # throw it away. None leaves the handshake unverified, exactly as before this field existed.
        try:
            ssh_host_key = self.parse_host_key()
        except Exception as e:
            raise Exception("SSHTunnel host key is not valid") from e

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
