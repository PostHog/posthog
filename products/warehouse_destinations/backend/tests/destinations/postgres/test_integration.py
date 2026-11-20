import pathlib

import pytest

import certifi
import psycopg

from posthog.models.integration import MISSING_CERT_PATH, TLS

from products.warehouse_destinations.backend.destinations.postgres.integration import InlineSSLMode, inline_tls

CERTIFI_BUNDLE = pathlib.Path(certifi.where()).read_text()


@pytest.mark.parametrize(
    "ssl_mode, libpq_version, root_cert",
    [
        # A missing root certificate file makes libpq encrypt without a check.
        ("require", 170000, MISSING_CERT_PATH),
        ("require", 150000, MISSING_CERT_PATH),
        ("verify-ca", 170000, "system"),
        ("verify-full", 160000, "system"),
        # libpq before 16 does not read "system", so it gets the certifi bundle.
        ("verify-ca", 150000, CERTIFI_BUNDLE),
        ("verify-full", 150000, CERTIFI_BUNDLE),
    ],
)
def test_inline_tls_verifies_against_a_trust_store_only_in_the_verify_modes(
    monkeypatch: pytest.MonkeyPatch, ssl_mode: InlineSSLMode, libpq_version: int, root_cert: str
) -> None:
    monkeypatch.setattr(psycopg.pq, "version", lambda: libpq_version)

    assert inline_tls(ssl_mode) == TLS(ssl_mode=ssl_mode, ssl_root_cert=root_cert)
