from datetime import UTC, datetime

import pytest
from unittest import mock

from rest_framework import status

from products.managed_warehouse.backend.service_credentials import (
    DEFAULT_CREDENTIAL_TTL_SECONDS,
    MAX_CREDENTIAL_TTL_SECONDS,
    MIN_CREDENTIAL_TTL_SECONDS,
    ServiceCredential,
    ServiceCredentialConnect,
    ServiceCredentialUnavailable,
    mint_service_credential,
    refresh_service_credential,
)

# Never a real secret: test payloads use this sentinel so assertion failures
# can be checked for containment/redaction without a live grant in the tree.
_FAKE_SECRET = "test-plaintext-sentinel-not-a-real-grant"

_CONNECT = {
    "host": "org-1.dw.us.postwh.com",
    "port": 443,
    "database": "ducklake",
    "sslmode": "require",
}


def _ok_response(data: dict) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status.HTTP_200_OK
    resp.data = data
    return resp


def _mint_payload(**overrides: object) -> dict:
    payload: dict = {
        "credential_id": "svc_a1b2c3d4e5f60718293a4b5c",
        "credential_secret": _FAKE_SECRET,
        "expires_at": "2026-08-11T13:00:00Z",
        "connect": _CONNECT,
    }
    payload.update(overrides)
    return payload


class TestMintServiceCredential:
    def test_threads_request_fields_to_cp(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(_mint_payload())

            credential = mint_service_credential("org-1", 7, principal="dagster:events-backfill", ttl_seconds=900)

        # credential_id is server-generated: svc_-prefixed, non-empty.
        assert credential.credential_id.startswith("svc_")
        assert len(credential.credential_id) > len("svc_")
        assert credential.credential_secret == _FAKE_SECRET
        assert credential.expires_at == datetime(2026, 8, 11, 13, 0, tzinfo=UTC)
        assert credential.connect == ServiceCredentialConnect(
            host="org-1.dw.us.postwh.com", port=443, database="ducklake", sslmode="require"
        )

        # Org-scoped route, org-scoped body: team_id is absorbed by the
        # signature for backwards compat but must NOT cross the wire.
        mock_request.assert_called_once_with(
            "POST",
            "org-1",
            "/service-credentials",
            json_body={
                "principal": "dagster:events-backfill",
                "ttl_seconds": 900,
            },
            require_enabled=False,
        )
        assert "team_id" not in mock_request.call_args.kwargs["json_body"]
        assert "team_id" not in mock_request.call_args.args[2]

    def test_ttl_is_clamped_to_cp_policy(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(_mint_payload())
            mint_service_credential("org-1", 7, principal="d", ttl_seconds=1)
            assert mock_request.call_args.kwargs["json_body"]["ttl_seconds"] == MIN_CREDENTIAL_TTL_SECONDS

            mint_service_credential("org-1", 7, principal="d", ttl_seconds=100_000)
            assert mock_request.call_args.kwargs["json_body"]["ttl_seconds"] == MAX_CREDENTIAL_TTL_SECONDS

            mint_service_credential("org-1", 7, principal="d")
            assert mock_request.call_args.kwargs["json_body"]["ttl_seconds"] == DEFAULT_CREDENTIAL_TTL_SECONDS

    def test_missing_secret_raises_unavailable(self):
        payload = _mint_payload()
        del payload["credential_secret"]
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(payload)
            with pytest.raises(ServiceCredentialUnavailable, match="credential_secret"):
                mint_service_credential("org-1", 7, principal="d")

    def test_cp_error_raises_unavailable(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            resp = mock.MagicMock()
            resp.status_code = status.HTTP_409_CONFLICT
            resp.data = {"error": "org warehouse is not provisioned"}
            mock_request.return_value = resp

            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                mint_service_credential("org-1", 99, principal="d")
            assert "409" in str(exc_info.value)

    def test_missing_credential_id_raises_unavailable(self):
        payload = _mint_payload()
        del payload["credential_id"]
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(payload)
            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                mint_service_credential("org-1", 7, principal="d")
            assert "credential_id" in str(exc_info.value)

    def test_bad_expires_at_raises_unavailable(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(_mint_payload(expires_at="not-a-timestamp"))
            with pytest.raises(ServiceCredentialUnavailable):
                mint_service_credential("org-1", 7, principal="d")

    def test_missing_connect_raises_unavailable(self):
        # A 2xx without `connect` is an older CP than the contract. The
        # conninfo builder no longer reads the DuckgresServer row on the
        # service-credential path, so there is nothing to fall back to HERE —
        # raise unavailable; the caller's broad fallback to root engages (the
        # established transitional degradation).
        payload = _mint_payload()
        del payload["connect"]
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(payload)
            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                mint_service_credential("org-1", 7, principal="d")
            assert "connect" in str(exc_info.value)

    @pytest.mark.parametrize(
        "connect",
        [
            {"port": 443, "database": "ducklake", "sslmode": "require"},  # no host
            {"host": "org-1.dw.us.postwh.com", "database": "ducklake", "sslmode": "require"},  # no port
            {"host": "org-1.dw.us.postwh.com", "port": "not-a-port", "database": "ducklake", "sslmode": "require"},
            {"host": "org-1.dw.us.postwh.com", "port": 443, "sslmode": "require"},  # no database
            {"host": "org-1.dw.us.postwh.com", "port": 443, "database": "ducklake"},  # no sslmode
            "not-a-dict",
        ],
    )
    def test_partial_connect_raises_unavailable(self, connect):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(_mint_payload(connect=connect))
            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                mint_service_credential("org-1", 7, principal="d")
            assert "connect" in str(exc_info.value)

    def test_malformed_connect_never_leaks_secret_in_exception(self):
        # Same redaction guarantee as the other malformed-response paths: a
        # payload rejected for its connect block can still carry a live
        # `credential_secret`, and the backfill's broad fallback logs
        # exception text. Assert via the redacted shape, never the raw
        # payload string.
        payload = _mint_payload()
        del payload["connect"]
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(payload)
            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                mint_service_credential("org-1", 7, principal="d")

            message = str(exc_info.value)
            assert _FAKE_SECRET not in message
            assert "<redacted>" in message

    def test_malformed_response_never_leaks_secret_in_exception(self):
        # The backfill's broad fallback logs the exception text — a malformed
        # CP payload that still carries a live `credential_secret` must not
        # surface it there.
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(_mint_payload(credential_id=""))
            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                mint_service_credential("org-1", 7, principal="d")

            message = str(exc_info.value)
            assert _FAKE_SECRET not in message
            assert "<redacted>" in message
            # ...while keeping the shape visible for debugging.
            assert "credential_secret" in message
            assert "expires_at" in message

    def test_error_status_body_is_redacted_too(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            resp = mock.MagicMock()
            resp.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            resp.data = {"error": "boom", "credential_secret": _FAKE_SECRET}
            mock_request.return_value = resp

            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                mint_service_credential("org-1", 7, principal="d")

            assert _FAKE_SECRET not in str(exc_info.value)

    def test_credential_dataclass_repr_never_shows_secret(self):
        # A dataclass repr lands in any traceback, pytest diff, or log line
        # that stringifies the object: the secret must be repr=False.
        credential = ServiceCredential(
            credential_id="svc_a1b2c3d4e5f60718293a4b5c",
            credential_secret=_FAKE_SECRET,
            expires_at=datetime(2026, 8, 11, 13, 0, tzinfo=UTC),
            connect=ServiceCredentialConnect(
                host="org-1.dw.us.postwh.com", port=443, database="ducklake", sslmode="require"
            ),
        )
        rendered = repr(credential)
        assert _FAKE_SECRET not in rendered
        assert "svc_a1b2c3d4e5f60718293a4b5c" in rendered  # the id is not a secret


class TestRefreshServiceCredential:
    def test_threads_request_fields_to_cp(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(_mint_payload())

            credential = refresh_service_credential("org-1", "svc_a1b2c3d4e5f60718293a4b5c", ttl_seconds=600)

        assert credential.credential_id == "svc_a1b2c3d4e5f60718293a4b5c"
        assert credential.credential_secret == _FAKE_SECRET
        assert credential.expires_at == datetime(2026, 8, 11, 13, 0, tzinfo=UTC)
        assert credential.connect == ServiceCredentialConnect(
            host="org-1.dw.us.postwh.com", port=443, database="ducklake", sslmode="require"
        )

        mock_request.assert_called_once_with(
            "POST",
            "org-1",
            "/service-credentials/refresh",
            json_body={
                "credential_id": "svc_a1b2c3d4e5f60718293a4b5c",
                "ttl_seconds": 600,
            },
            require_enabled=False,
        )

    def test_ttl_is_clamped_and_defaults(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(_mint_payload())
            refresh_service_credential("org-1", "svc_x", ttl_seconds=1)
            assert mock_request.call_args.kwargs["json_body"]["ttl_seconds"] == MIN_CREDENTIAL_TTL_SECONDS

            refresh_service_credential("org-1", "svc_x", ttl_seconds=100_000)
            assert mock_request.call_args.kwargs["json_body"]["ttl_seconds"] == MAX_CREDENTIAL_TTL_SECONDS

            refresh_service_credential("org-1", "svc_x")
            assert mock_request.call_args.kwargs["json_body"]["ttl_seconds"] == DEFAULT_CREDENTIAL_TTL_SECONDS

    def test_cp_error_raises_unavailable(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            resp = mock.MagicMock()
            resp.status_code = status.HTTP_404_NOT_FOUND
            resp.data = {"error": "unknown or lapsed credential"}
            mock_request.return_value = resp

            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                refresh_service_credential("org-1", "svc_gone")
            assert "404" in str(exc_info.value)
            # credential_id is not a secret; naming it in the error is fine.
            assert "svc_gone" in str(exc_info.value)

    def test_missing_credential_id_raises_unavailable(self):
        payload = _mint_payload()
        del payload["credential_id"]
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(payload)
            with pytest.raises(ServiceCredentialUnavailable):
                refresh_service_credential("org-1", "svc_x")

    def test_bad_expires_at_raises_unavailable(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(_mint_payload(expires_at="not-a-timestamp"))
            with pytest.raises(ServiceCredentialUnavailable):
                refresh_service_credential("org-1", "svc_x")

    def test_missing_connect_raises_unavailable(self):
        payload = _mint_payload()
        del payload["connect"]
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(payload)
            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                refresh_service_credential("org-1", "svc_x")
            assert "connect" in str(exc_info.value)

    def test_error_status_body_is_redacted_too(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            resp = mock.MagicMock()
            resp.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            resp.data = {"error": "boom", "credential_secret": _FAKE_SECRET}
            mock_request.return_value = resp

            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                refresh_service_credential("org-1", "svc_x")

            assert _FAKE_SECRET not in str(exc_info.value)

    def test_malformed_response_never_leaks_secret_in_exception(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(_mint_payload(credential_id=""))
            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                refresh_service_credential("org-1", "svc_x")

            message = str(exc_info.value)
            assert _FAKE_SECRET not in message
            assert "<redacted>" in message
