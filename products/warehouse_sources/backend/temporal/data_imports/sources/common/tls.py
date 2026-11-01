import ssl
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import field
from functools import cache
from pathlib import Path

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigConverter,
    SourceFieldSelectConfigOption,
)

CLIENT_CERTIFICATE_INCOMPLETE_ERROR = (
    "A client certificate needs its private key. Add the key, or clear the certificate."
)

ENCRYPTED_CLIENT_KEY_ERROR = "The client key has a passphrase. Remove the passphrase and paste the key again."

# The user has to change the source to clear either one, so a sync stops on them.
TLS_CONFIGURATION_ERRORS: dict[str, str | None] = {
    CLIENT_CERTIFICATE_INCOMPLETE_ERROR: None,
    ENCRYPTED_CLIENT_KEY_ERROR: None,
}

_INVALID_CA_CERTIFICATE_ERROR = (
    "The certificate authority you configured isn't a valid PEM certificate. Paste the complete "
    "certificate (including the BEGIN/END lines), or remove it and turn off certificate "
    "verification instead."
)

_CLIENT_CERTIFICATE_REJECTED_ERROR = (
    "Your database rejected the client certificate, or requires one. Add a client certificate and key that "
    "your database trusts."
)

# Keyed by the stable part of the client library's message, in lower case. Each failure stays the same
# on every attempt until the user changes the source.
CERTIFICATE_ERRORS: dict[str, str] = {
    "certificate verify failed": (
        "PostHog could not verify your database's TLS certificate. Either an authority PostHog trusts did not "
        "sign it, or it does not match the host. Add the authority that signed it, check the host, or turn "
        "off certificate verification and remove the certificate authority."
    ),
    "does not match host name": (
        "Your database's TLS certificate does not match the host you entered. Use the hostname the "
        "certificate was issued for, or turn off certificate verification and remove the certificate authority."
    ),
    "alert certificate required": _CLIENT_CERTIFICATE_REJECTED_ERROR,
    "alert bad certificate": _CLIENT_CERTIFICATE_REJECTED_ERROR,
    "alert unknown ca": _CLIENT_CERTIFICATE_REJECTED_ERROR,
    # Postgres completes the TLS handshake and then rejects the certificate at its pg_hba check.
    "certificate authentication failed": _CLIENT_CERTIFICATE_REJECTED_ERROR,
    "connection requires a valid client certificate": _CLIENT_CERTIFICATE_REJECTED_ERROR,
    # libpq fails to load the file `tls_files` wrote for the "Certificate authority" field when its
    # content isn't a parseable PEM certificate (empty, truncated, or not a certificate at all). The
    # raw message also names the per-run temp file path, so match the stable OpenSSL reason instead.
    "no certificate or crl found": _INVALID_CA_CERTIFICATE_ERROR,
    # libpq words every unreadable CA file this way, whatever OpenSSL's reason is (a truncated
    # certificate reports "bad end line", not the reason above).
    "could not read root certificate file": _INVALID_CA_CERTIFICATE_ERROR,
}


class TLSConfigurationError(Exception):
    """The TLS fields of a source contradict each other."""


@frozen
class TLSOptions:
    """The TLS settings a database source reads from its config.

    `verify_hostname` is False through an SSH tunnel. The tunnel presents the database on a
    loopback address, so the certificate's hostname cannot match the address the client dials.
    """

    verify: bool = False
    verify_hostname: bool = False
    ca_certificate: str | None = None
    client_certificate: str | None = None
    client_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.client_certificate and not self.client_key:
            raise TLSConfigurationError(CLIENT_CERTIFICATE_INCOMPLETE_ERROR)
        # OpenSSL prompts on the terminal for the passphrase of an encrypted key, which can block
        # a worker. Both PEM forms of an encrypted key carry this word.
        if self.client_key and "ENCRYPTED" in self.client_key:
            raise TLSConfigurationError(ENCRYPTED_CLIENT_KEY_ERROR)

    @property
    def is_set(self) -> bool:
        return self.verify or bool(self.client_certificate)


@frozen
class TLSFiles:
    ca_certificate: str | None
    client_certificate: str | None
    client_key: str | None


def tls_options(config: object) -> TLSOptions:
    """Read the TLS fields from a source config. A config without them gets the no-op options."""
    ca_certificate = _pem(config, "ca_certificate")
    client_certificate = _pem(config, "client_certificate")
    # A certificate authority has no use except to verify against, so setting one turns verification on.
    verify = bool(getattr(config, "verify_server_certificate", False)) or ca_certificate is not None
    ssh_tunnel = getattr(config, "ssh_tunnel", None)
    return TLSOptions(
        verify=verify,
        verify_hostname=verify and not (ssh_tunnel is not None and ssh_tunnel.enabled),
        ca_certificate=ca_certificate,
        client_certificate=client_certificate,
        # The form cannot blank a stored secret, so clearing the certificate is how a user turns the
        # client certificate off. The stored key stays, and nothing uses it without a certificate.
        client_key=_pem(config, "client_key") if client_certificate else None,
    )


# Debian and Ubuntu first, the production images. macOS and Alpine second.
_CA_BUNDLE_PATHS = ("/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cert.pem")


@cache
def system_ca_bundle() -> str:
    """Return the first CA bundle that exists on this host."""
    defaults = ssl.get_default_verify_paths()
    for path in (*_CA_BUNDLE_PATHS, defaults.cafile, defaults.openssl_cafile):
        if path and Path(path).is_file():
            return path
    return _CA_BUNDLE_PATHS[0]


@contextmanager
def tls_files(options: TLSOptions) -> Iterator[TLSFiles]:
    """Write the PEM values to files for the duration of the context.

    The database clients take certificate paths, not contents. The directory is private to this
    process user, which libpq requires for the private key.
    """
    if not (options.ca_certificate or options.client_certificate):
        yield TLSFiles(ca_certificate=None, client_certificate=None, client_key=None)
        return
    with tempfile.TemporaryDirectory(prefix="source-tls-") as directory:

        def write(name: str, pem: str | None) -> str | None:
            if not pem:
                return None
            path = Path(directory) / name
            path.touch(mode=0o600)
            path.write_text(pem)
            return str(path)

        yield TLSFiles(
            ca_certificate=write("ca.crt", options.ca_certificate),
            client_certificate=write("client.crt", options.client_certificate),
            client_key=write("client.key", options.client_key),
        )


@contextmanager
def libpq_tls_kwargs(options: TLSOptions | None) -> Iterator[dict[str, str]]:
    """Yield the libpq connection parameters that `options` overrides.

    Yields nothing when no TLS option is set, so the caller's own `sslmode` stays in effect.
    The files exist only inside the context, and libpq reads them when it connects.
    """
    if options is None or not options.is_set:
        yield {}
        return
    with tls_files(options) as files:
        kwargs: dict[str, str] = {}
        if options.verify:
            kwargs["sslmode"] = "verify-full" if options.verify_hostname else "verify-ca"
            kwargs["sslrootcert"] = files.ca_certificate or system_ca_bundle()
        if files.client_certificate and files.client_key:
            # With `prefer`, libpq falls back to plaintext and never presents the certificate.
            kwargs.setdefault("sslmode", "require")
            kwargs["sslcert"] = files.client_certificate
            kwargs["sslkey"] = files.client_key
        yield kwargs


def _pem(config: object, name: str) -> str | None:
    value = getattr(config, name, None)
    return value.strip() or None if isinstance(value, str) else None


def verify_server_certificate_field() -> SourceFieldSelectConfig:
    return SourceFieldSelectConfig(
        name="verify_server_certificate",
        label="Verify the server certificate?",
        required=True,
        defaultValue="false",
        converter=SourceFieldSelectConfigConverter.STR_TO_BOOL,
        caption=(
            "Check that your database's TLS certificate comes from a trusted authority and matches the host. "
            "Through an SSH tunnel we check the certificate chain but not the hostname, because the tunnel "
            "presents your database on a local address."
        ),
        options=[
            SourceFieldSelectConfigOption(label="Yes", value="true"),
            SourceFieldSelectConfigOption(label="No", value="false"),
        ],
    )


def ca_certificate_field() -> SourceFieldInputConfig:
    return SourceFieldInputConfig(
        name="ca_certificate",
        label="Certificate authority (optional)",
        type=SourceFieldInputConfigType.TEXTAREA,
        required=False,
        placeholder="-----BEGIN CERTIFICATE-----",
        caption=(
            "The PEM certificate of the authority that signed your database's certificate. Add it when your "
            "database uses a private authority or a self-signed certificate. Adding one turns on certificate "
            "verification."
        ),
        secret=False,
    )


def client_certificate_fields() -> list[SourceFieldInputConfig]:
    return [
        SourceFieldInputConfig(
            name="client_certificate",
            label="Client certificate (optional)",
            type=SourceFieldInputConfigType.TEXTAREA,
            required=False,
            placeholder="-----BEGIN CERTIFICATE-----",
            caption="A PEM certificate that PostHog presents to your database. Add it when your database requires one.",
            secret=False,
        ),
        SourceFieldInputConfig(
            name="client_key",
            label="Client key (optional)",
            type=SourceFieldInputConfigType.TEXTAREA,
            required=False,
            placeholder="-----BEGIN PRIVATE KEY-----",
            caption="The private key of the client certificate, in PEM format and without a passphrase.",
            secret=True,
        ),
    ]
