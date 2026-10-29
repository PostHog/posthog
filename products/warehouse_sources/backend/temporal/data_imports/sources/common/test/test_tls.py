import os
import stat
from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.tls import (
    TLSConfigurationError,
    libpq_tls_kwargs,
    system_ca_bundle,
    tls_options,
)

_TUNNEL = SimpleNamespace(enabled=True)


class TestLibpqTLSKwargs(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_tls_fields", {}, None, None, None),
            ("blank_fields", {"verify_server_certificate": False, "ca_certificate": "  "}, None, None, None),
            ("verify", {"verify_server_certificate": True}, "verify-full", "system", None),
            (
                "verify_through_tunnel",
                {"verify_server_certificate": True, "ssh_tunnel": _TUNNEL},
                "verify-ca",
                "system",
                None,
            ),
            ("ca_alone_turns_verification_on", {"ca_certificate": "CA PEM"}, "verify-full", "CA PEM", None),
            (
                "client_certificate_alone",
                {"client_certificate": "CERT PEM", "client_key": "KEY PEM"},
                "require",
                None,
                ("CERT PEM", "KEY PEM"),
            ),
            ("cleared_certificate_ignores_the_stored_key", {"client_key": "KEY PEM"}, None, None, None),
        ]
    )
    def test_overrides(
        self,
        _name: str,
        fields: dict[str, object],
        expected_sslmode: str | None,
        expected_root: str | None,
        expected_client: tuple[str, str] | None,
    ) -> None:
        with libpq_tls_kwargs(tls_options(SimpleNamespace(**fields))) as kwargs:
            written = [Path(value) for key, value in kwargs.items() if key != "sslmode" and value != system_ca_bundle()]
            root = kwargs.get("sslrootcert")
            actual_root = "system" if root == system_ca_bundle() else root and Path(root).read_text()
            actual_client = (
                (Path(kwargs["sslcert"]).read_text(), Path(kwargs["sslkey"]).read_text())
                if "sslcert" in kwargs
                else None
            )
            assert (kwargs.get("sslmode"), actual_root, actual_client) == (
                expected_sslmode,
                expected_root,
                expected_client,
            )
            assert all(stat.S_IMODE(os.stat(path).st_mode) == 0o600 for path in written if path.name == "client.key")

        assert not any(path.exists() for path in written)

    @parameterized.expand(
        [
            ("certificate_without_key", {"client_certificate": "CERT PEM"}),
            (
                "encrypted_key",
                {"client_certificate": "CERT PEM", "client_key": "-----BEGIN ENCRYPTED PRIVATE KEY-----"},
            ),
        ]
    )
    def test_unusable_client_certificate_is_refused(self, _name: str, fields: dict[str, str]) -> None:
        with self.assertRaises(TLSConfigurationError):
            tls_options(SimpleNamespace(**fields))
