import typing
import logging
import dataclasses
from io import StringIO
from typing import IO, Literal

from cryptography.hazmat.primitives import serialization as crypto_serialization
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed25519, rsa
from paramiko import DSSKey, ECDSAKey, Ed25519Key, PKey, RSAKey
from sshtunnel import BaseSSHTunnelForwarderError, SSHTunnelForwarder

from products.warehouse_sources.backend.temporal.data_imports.sources.common import config

# sshtunnel funnels the specific reason a tunnel failed to open (gateway unreachable, DNS
# failure, auth rejected, forwarding refused) into ERROR-level log records inside
# `_create_tunnels` / `_connect_to_gateway`, then raises a generic
# `BaseSSHTunnelForwarderError("Could not establish session to SSH gateway")` that discards
# which one it was. That opaque string is what reaches the customer, leaving them nothing to
# debug. `_DetailCapturingForwarder` records those messages and folds the real reason into the
# raised exception so the connection-test / sync error surfaces it instead.
_GENERIC_GATEWAY_REASON = "Could not establish session to SSH gateway"


class _TunnelErrorCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    @property
    def detail(self) -> str | None:
        # The most recent ERROR record is the most specific failure (gateway connect / auth /
        # forwarding). sshtunnel doesn't log the generic "Could not establish session" reason
        # itself, so any captured record is useful signal — return the last one.
        relevant = [m for m in self.messages if m and _GENERIC_GATEWAY_REASON not in m]
        return relevant[-1] if relevant else None


class _DetailCapturingForwarder(SSHTunnelForwarder):
    """`SSHTunnelForwarder` that augments the generic gateway error with the captured reason."""

    def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        self._error_capture = _TunnelErrorCapture()
        # A standalone `Logger` (not via `getLogger`) so we don't accumulate handlers across
        # instances or propagate sshtunnel's chatter to the root logger.
        capture_logger = logging.Logger(f"{__name__}.sshtunnel")
        capture_logger.addHandler(self._error_capture)
        kwargs["logger"] = capture_logger
        super().__init__(*args, **kwargs)

    def start(self) -> None:
        try:
            super().start()
        except BaseSSHTunnelForwarderError as e:
            detail = self._error_capture.detail
            if detail and detail not in str(e.value):
                raise BaseSSHTunnelForwarderError(value=f"{e.value}: {detail}") from e
            raise


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
    except ValueError:
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


@dataclasses.dataclass
class SSHTunnel:
    enabled: bool

    host: str
    port: int | str
    auth_type: Literal["password", "keypair"]
    username: str | None
    password: str | None
    private_key: str | None
    passphrase: str | None

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
        )

    def parse_private_key(self) -> PKey:
        if self.passphrase is None:
            passphrase = None
        elif len(self.passphrase) == 0:
            passphrase = None
        else:
            passphrase = self.passphrase

        return from_private_key(StringIO(self.private_key), passphrase)

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
            except:
                # TODO: More helpful error messages
                return False, "Private key could not be parsed"

            return True, ""

        return False, ""  # type: ignore

    def has_valid_port(self) -> tuple[bool, str]:
        port = int(self.port)
        if port == 80 or port == 443:
            return False, f"Port {port} is not allowed"

        return True, ""

    def get_tunnel(self, remote_host: str, remote_port: int) -> SSHTunnelForwarder:
        if not self.is_auth_valid()[0]:
            raise Exception("SSHTunnel auth is not valid")

        if not self.has_valid_port()[0]:
            raise Exception("SSHTunnel port is not valid")

        if self.auth_type == "password":
            return _DetailCapturingForwarder(
                (self.host, int(self.port)),
                ssh_username=self.username,
                ssh_password=self.password,
                remote_bind_address=(remote_host, remote_port),
                local_bind_address=("127.0.0.1",),
            )
        else:
            return _DetailCapturingForwarder(
                (self.host, int(self.port)),
                ssh_username=self.username,
                ssh_pkey=self.parse_private_key(),
                ssh_private_key_password=self.passphrase,
                remote_bind_address=(remote_host, remote_port),
                local_bind_address=("127.0.0.1",),
            )
