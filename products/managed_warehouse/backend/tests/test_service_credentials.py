from datetime import UTC, datetime

import pytest
from unittest import mock

from rest_framework import status

from products.managed_warehouse.backend.service_credentials import (
    DEFAULT_CREDENTIAL_TTL_SECONDS,
    MAX_CREDENTIAL_TTL_SECONDS,
    MIN_CREDENTIAL_TTL_SECONDS,
    ServiceCredentialUnavailable,
    mint_service_credential,
)


def _ok_response(data: dict) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status.HTTP_200_OK
    resp.data = data
    return resp


class TestMintServiceCredential:
    def test_threads_request_fields_to_cp(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(
                {
                    "username": "posthog_team_7_rw",
                    "password": "minted-plaintext",
                    "expires_at": "2026-08-11T13:00:00Z",
                }
            )

            credential = mint_service_credential(
                "org-1", 7, principal="dagster:events-backfill", ttl_seconds=900, force_rotate=True
            )

        assert credential.username == "posthog_team_7_rw"
        assert credential.password == "minted-plaintext"
        assert credential.rotated is True
        assert credential.expires_at == datetime(2026, 8, 11, 13, 0, tzinfo=UTC)

        mock_request.assert_called_once_with(
            "POST",
            "org-1",
            "/teams/7/service-credentials",
            json_body={
                "team_id": 7,
                "principal": "dagster:events-backfill",
                "ttl_seconds": 900,
                "force_rotate": True,
            },
            require_enabled=False,
        )

    def test_ttl_is_clamped_to_cp_policy(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(
                {
                    "username": "posthog_team_7_rw",
                    "password": "p",
                    "expires_at": "2026-08-11T13:00:00Z",
                }
            )
            mint_service_credential("org-1", 7, principal="d", ttl_seconds=1, force_rotate=True)
            assert mock_request.call_args.kwargs["json_body"]["ttl_seconds"] == MIN_CREDENTIAL_TTL_SECONDS

            mint_service_credential("org-1", 7, principal="d", ttl_seconds=100_000, force_rotate=True)
            assert mock_request.call_args.kwargs["json_body"]["ttl_seconds"] == MAX_CREDENTIAL_TTL_SECONDS

            mint_service_credential("org-1", 7, principal="d", force_rotate=True)
            assert mock_request.call_args.kwargs["json_body"]["ttl_seconds"] == DEFAULT_CREDENTIAL_TTL_SECONDS

    def test_reuse_path_reports_missing_password(self):
        # When the CP reuses a live grant it omits the password — the caller
        # sees credential.password == "" and rotated == False and must mint
        # with force_rotate if it has nothing cached.
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(
                {
                    "username": "posthog_team_7_rw",
                    # no "password" key — what the CP actually returns on reuse
                    "expires_at": "2026-08-11T13:00:00Z",
                }
            )
            credential = mint_service_credential("org-1", 7, principal="d")

        assert credential.password == ""
        assert credential.rotated is False

    def test_cp_error_raises_unavailable(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            resp = mock.MagicMock()
            resp.status_code = status.HTTP_409_CONFLICT
            resp.data = {"error": "project login requires an enabled org team"}
            mock_request.return_value = resp

            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                mint_service_credential("org-1", 99, principal="d", force_rotate=True)
            assert "409" in str(exc_info.value)

    def test_missing_username_raises_unavailable(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response({"expires_at": "2026-08-11T13:00:00Z"})
            with pytest.raises(ServiceCredentialUnavailable):
                mint_service_credential("org-1", 7, principal="d", force_rotate=True)

    def test_bad_expires_at_raises_unavailable(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(
                {"username": "u", "password": "p", "expires_at": "not-a-timestamp"}
            )
            with pytest.raises(ServiceCredentialUnavailable):
                mint_service_credential("org-1", 7, principal="d", force_rotate=True)

    def test_malformed_response_never_leaks_password_in_exception(self):
        # The backfill's broad fallback logs the exception text — a malformed
        # CP payload that still carries a live `password` must not surface it
        # there (review follow-up on #81289).
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            mock_request.return_value = _ok_response(
                {"username": "", "password": "live-grant-plaintext", "expires_at": "2026-08-11T13:00:00Z"}
            )
            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                mint_service_credential("org-1", 7, principal="d", force_rotate=True)

            message = str(exc_info.value)
            assert "live-grant-plaintext" not in message
            assert "<redacted>" in message
            # ...while keeping the shape visible for debugging.
            assert "password" in message
            assert "expires_at" in message

    def test_error_status_body_is_redacted_too(self):
        with mock.patch("products.managed_warehouse.backend.presentation.views._request") as mock_request:
            resp = mock.MagicMock()
            resp.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            resp.data = {"error": "boom", "password": "leaked-in-error-body"}
            mock_request.return_value = resp

            with pytest.raises(ServiceCredentialUnavailable) as exc_info:
                mint_service_credential("org-1", 7, principal="d", force_rotate=True)

            assert "leaked-in-error-body" not in str(exc_info.value)
