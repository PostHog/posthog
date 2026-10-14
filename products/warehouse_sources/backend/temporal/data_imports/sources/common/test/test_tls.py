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
            ("no_tls_fields", {}, None, False),
            ("blank_fields", {"verify_server_certificate": False, "ca_certificate": "  "}, None, False),
            ("verify", {"verify_server_certificate": True}, "verify-full", False),
            ("verify_through_tunnel", {"verify_server_certificate": True, "ssh_tunnel": _TUNNEL}, "verify-ca", False),
            ("ca_alone_turns_verification_on", {"ca_certificate": "CA PEM"}, "verify-full", False),
            ("client_certificate_alone", {"client_certificate": "CERT PEM", "client_key": "KEY PEM"}, None, True),
            ("cleared_certificate_ignores_the_stored_key", {"client_key": "KEY PEM"}, None, False),
        ]
    )
    def test_overrides(
        self, _name: str, fields: dict[str, object], expected_sslmode: str | None, expects_client_certificate: bool
    ) -> None:
        with libpq_tls_kwargs(tls_options(SimpleNamespace(**fields))) as kwargs:
            assert kwargs.get("sslmode") == expected_sslmode
            assert ("sslcert" in kwargs) is expects_client_certificate
            if expected_sslmode is None:
                assert "sslrootcert" not in kwargs
            elif "CA PEM" in str(fields.get("ca_certificate")):
                assert Path(kwargs["sslrootcert"]).read_text() == "CA PEM"
            else:
                assert kwargs["sslrootcert"] == system_ca_bundle()
            if expects_client_certificate:
                assert Path(kwargs["sslcert"]).read_text() == "CERT PEM"
                assert Path(kwargs["sslkey"]).read_text() == "KEY PEM"
                assert stat.S_IMODE(os.stat(kwargs["sslkey"]).st_mode) == 0o600
            written = [value for key, value in kwargs.items() if key != "sslmode" and value != system_ca_bundle()]

        assert not any(Path(path).exists() for path in written)

    def test_certificate_without_key_is_refused(self) -> None:
        with self.assertRaises(TLSConfigurationError):
            tls_options(SimpleNamespace(client_certificate="CERT PEM"))

    def test_system_ca_bundle_exists_on_this_host(self) -> None:
        assert Path(system_ca_bundle()).is_file()
