import datetime as dt
from collections.abc import Iterable
from typing import Any, Optional, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.docusign import (
    PAGE_SIZE,
    DocusignAuthError,
    DocusignCredentials,
    DocusignResumeConfig,
    _default_from_date,
    _to_iso8601,
    docusign_source,
    get_rows,
    mint_access_token,
    resolve_account,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.tests.conftest import (
    PRIVATE_KEY_PEM,
    FakeResponse,
    FakeResumeManager,
    FakeSession,
)

_SESSION_FACTORY = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.docusign.docusign.make_tracked_session"
)

USERINFO_PAYLOAD: dict[str, Any] = {
    "sub": "user-guid",
    "accounts": [
        {"account_id": "111", "is_default": False, "account_name": "Old", "base_uri": "https://na2.docusign.net"},
        {"account_id": "222", "is_default": True, "account_name": "Main", "base_uri": "https://na3.docusign.net/"},
    ],
}

TOKEN_PAYLOAD: dict[str, Any] = {"access_token": "tok-1", "expires_in": 3600, "token_type": "Bearer"}


def jwt_credentials(**overrides: Any) -> DocusignCredentials:
    defaults: dict[str, Any] = {
        "environment": "production",
        "selection": "jwt",
        "integration_key": "int-key",
        "user_id": "user-guid",
        "private_key": PRIVATE_KEY_PEM,
    }
    defaults.update(overrides)
    return DocusignCredentials(**defaults)


def refresh_credentials(**overrides: Any) -> DocusignCredentials:
    defaults: dict[str, Any] = {
        "environment": "demo",
        "selection": "refresh_token",
        "integration_key": "int-key",
        "secret_key": "sek-ret",
        "refresh_token": "ref-tok",
    }
    defaults.update(overrides)
    return DocusignCredentials(**defaults)


def envelope_page(count: int, offset: int = 0, next_uri: Optional[str] = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "envelopes": [
            {
                "envelopeId": f"env-{offset + i}",
                "status": "completed",
                "createdDateTime": "2024-01-01T00:00:00.0000000Z",
                "statusChangedDateTime": "2024-02-01T00:00:00.0000000Z",
            }
            for i in range(count)
        ],
        "resultSetSize": str(count),
        "startPosition": str(offset),
    }
    if next_uri is not None:
        body["nextUri"] = next_uri
    return body


def run_rows(
    session: FakeSession,
    credentials: DocusignCredentials,
    endpoint: str,
    logger: FilteringBoundLogger,
    manager: Optional[FakeResumeManager] = None,
    **kwargs: Any,
) -> tuple[list[list[dict[str, Any]]], FakeResumeManager]:
    resume_manager = manager or FakeResumeManager()
    with mock.patch(_SESSION_FACTORY, return_value=session):
        batches = list(
            get_rows(
                credentials=credentials,
                endpoint_name=endpoint,
                start_date=kwargs.pop("start_date", None),
                resumable_source_manager=resume_manager,
                logger=logger,
                **kwargs,
            )
        )
    return batches, resume_manager


class TestDocusignTransport:
    def test_refresh_token_grant_uses_basic_auth_with_the_integration_key(self) -> None:
        session = FakeSession(post_responses=[FakeResponse(200, TOKEN_PAYLOAD)])

        mint_access_token(session.as_session(), refresh_credentials())

        url, kwargs = session.post_calls[0]
        assert url == "https://account-d.docusign.com/oauth/token"
        assert kwargs["data"] == {"grant_type": "refresh_token", "refresh_token": "ref-tok"}
        assert kwargs["auth"].username == "int-key"
        assert kwargs["auth"].password == "sek-ret"

    @pytest.mark.parametrize(
        "credentials,expected",
        [
            (jwt_credentials(private_key=None), "RSA private key"),
            (jwt_credentials(user_id=None), "impersonated user ID"),
            (refresh_credentials(refresh_token=None), "refresh token"),
            (refresh_credentials(secret_key=None), "secret key"),
        ],
    )
    def test_incomplete_credentials_fail_before_any_request(
        self, credentials: DocusignCredentials, expected: str
    ) -> None:
        session = FakeSession()

        with pytest.raises(DocusignAuthError) as excinfo:
            mint_access_token(session.as_session(), credentials)

        assert expected in str(excinfo.value)
        assert session.post_calls == []

    @pytest.mark.parametrize(
        "payload,expected_fragment",
        [
            ({"error": "consent_required"}, "error=consent_required"),
            ({"error": "invalid_grant", "error_description": "no soup"}, "error=invalid_grant"),
        ],
    )
    def test_token_errors_surface_docusigns_error_code(self, payload: dict[str, Any], expected_fragment: str) -> None:
        session = FakeSession(post_responses=[FakeResponse(400, payload)])

        with pytest.raises(DocusignAuthError) as excinfo:
            mint_access_token(session.as_session(), jwt_credentials())

        assert expected_fragment in str(excinfo.value)

    def test_token_response_without_access_token_is_an_auth_error(self) -> None:
        session = FakeSession(post_responses=[FakeResponse(200, {"expires_in": 3600})])

        with pytest.raises(DocusignAuthError):
            mint_access_token(session.as_session(), jwt_credentials())

    @pytest.mark.parametrize(
        "payload,account_id",
        [
            ({"accounts": []}, None),
            (USERINFO_PAYLOAD, "999"),
        ],
    )
    def test_resolve_account_rejects_unreachable_accounts(
        self, payload: dict[str, Any], account_id: Optional[str]
    ) -> None:
        session = FakeSession(get_responses=[FakeResponse(200, payload)])

        with pytest.raises(DocusignAuthError):
            resolve_account(session.as_session(), jwt_credentials(account_id=account_id), "tok-1")

    def test_resume_starts_from_the_saved_offset(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[FakeResponse(200, USERINFO_PAYLOAD), FakeResponse(200, envelope_page(1, offset=400))],
        )

        _, manager = run_rows(
            session,
            jwt_credentials(),
            "envelopes",
            logger,
            manager=FakeResumeManager(DocusignResumeConfig(start_position=400)),
        )

        envelope_url = next(url for url, _ in session.get_calls if "/envelopes" in url)
        assert parse_qs(urlparse(envelope_url).query)["start_position"] == ["400"]
        assert manager.cleared is True

    def test_expired_access_token_is_reminted_once(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            post_responses=[
                FakeResponse(200, TOKEN_PAYLOAD),
                FakeResponse(200, {"access_token": "tok-2"}),
            ],
            get_responses=[
                FakeResponse(200, USERINFO_PAYLOAD),
                FakeResponse(401, {"errorCode": "USER_AUTHENTICATION_FAILED"}),
                FakeResponse(200, envelope_page(1)),
            ],
        )

        batches, _ = run_rows(session, jwt_credentials(), "envelopes", logger)

        assert len(batches) == 1
        assert len(session.post_calls) == 2
        retried_headers = session.get_calls[-1][1]["headers"]
        assert retried_headers["Authorization"] == "Bearer tok-2"

    def test_persistent_api_error_is_raised(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[
                FakeResponse(200, USERINFO_PAYLOAD),
                FakeResponse(403, {"errorCode": "USER_LACKS_PERMISSIONS"}),
            ],
        )

        with pytest.raises(requests.HTTPError):
            run_rows(session, jwt_credentials(), "envelopes", logger)

    def test_recipients_are_flattened_out_of_every_role_bucket(self, logger: FilteringBoundLogger) -> None:
        page = envelope_page(1)
        page["envelopes"][0]["recipients"] = {
            "signers": [{"recipientId": "1", "email": "a@example.com"}],
            "carbonCopies": [{"recipientId": "2", "email": "b@example.com"}],
            "recipientCount": "2",
        }
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[FakeResponse(200, USERINFO_PAYLOAD), FakeResponse(200, page)],
        )

        batches, _ = run_rows(session, jwt_credentials(), "envelope_recipients", logger)

        rows = batches[0]
        assert [row["recipientType"] for row in rows] == ["signers", "carbonCopies"]
        assert {row["envelopeId"] for row in rows} == {"env-0"}
        assert rows[0]["envelopeStatusChangedDateTime"] == "2024-02-01T00:00:00.0000000Z"
        assert rows[0]["envelopeCreatedDateTime"] == "2024-01-01T00:00:00.0000000Z"
        query = parse_qs(urlparse(session.get_calls[-1][0]).query)
        assert query["include"] == ["recipients"]

    @pytest.mark.parametrize("child_key", ["envelopeDocuments", "documents"])
    def test_documents_are_flattened_under_either_key_docusign_uses(
        self, child_key: str, logger: FilteringBoundLogger
    ) -> None:
        page = envelope_page(1)
        page["envelopes"][0][child_key] = [{"documentId": "1", "name": "contract.pdf"}]
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[FakeResponse(200, USERINFO_PAYLOAD), FakeResponse(200, page)],
        )

        batches, _ = run_rows(session, jwt_credentials(), "envelope_documents", logger)

        assert batches[0] == [
            {
                "documentId": "1",
                "name": "contract.pdf",
                "envelopeId": "env-0",
                "envelopeCreatedDateTime": "2024-01-01T00:00:00.0000000Z",
                "envelopeStatusChangedDateTime": "2024-02-01T00:00:00.0000000Z",
            }
        ]

    def test_envelopes_without_children_yield_no_rows_but_still_paginate(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[
                FakeResponse(200, USERINFO_PAYLOAD),
                FakeResponse(200, envelope_page(PAGE_SIZE, next_uri="/restapi/next")),
                FakeResponse(200, envelope_page(1, offset=PAGE_SIZE)),
            ],
        )

        batches, manager = run_rows(session, jwt_credentials(), "envelope_recipients", logger)

        assert batches == []
        assert [state.start_position for state in manager.saved] == [PAGE_SIZE]

    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, None),
            (True, None),
            ("", None),
            ("2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
            (dt.datetime(2024, 3, 2, 4, 5, 6), "2024-03-02T04:05:06Z"),
            (
                dt.datetime(2024, 3, 2, 4, 5, 6, tzinfo=dt.timezone(dt.timedelta(hours=2))),
                "2024-03-02T02:05:06Z",
            ),
            (dt.date(2024, 3, 2), "2024-03-02T00:00:00Z"),
        ],
    )
    def test_watermark_coercion(self, value: Any, expected: Optional[str]) -> None:
        assert _to_iso8601(value) == expected

    def test_default_from_date_falls_back_to_a_bounded_lookback(self) -> None:
        fallback = _default_from_date(None)

        parsed = dt.datetime.strptime(fallback, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
        assert dt.datetime.now(dt.UTC) - parsed > dt.timedelta(days=700)
        assert _default_from_date("  2020-06-01T00:00:00Z ") == "2020-06-01T00:00:00Z"

    def test_validate_credentials_reports_docusign_error_text(self) -> None:
        session = FakeSession(post_responses=[FakeResponse(400, {"error": "consent_required"})])

        with mock.patch(_SESSION_FACTORY, return_value=session):
            valid, message = validate_credentials(jwt_credentials())

        assert valid is False
        assert message is not None and "consent_required" in message

    def test_validate_credentials_succeeds_when_an_account_resolves(self) -> None:
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[FakeResponse(200, USERINFO_PAYLOAD)],
        )

        with mock.patch(_SESSION_FACTORY, return_value=session):
            assert validate_credentials(jwt_credentials()) == (True, None)

    def test_validate_credentials_swallows_transport_failures(self) -> None:
        with mock.patch(_SESSION_FACTORY, side_effect=requests.ConnectionError("boom")):
            valid, message = validate_credentials(jwt_credentials())

        assert valid is False
        assert message == "Could not reach DocuSign with the provided credentials."

    def test_unknown_environment_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            _ = jwt_credentials(environment="staging").auth_host

    def test_source_response_items_are_lazy(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[FakeResponse(200, USERINFO_PAYLOAD), FakeResponse(200, envelope_page(2))],
        )

        response = docusign_source(
            credentials=jwt_credentials(),
            endpoint_name="envelopes",
            start_date=None,
            resumable_source_manager=FakeResumeManager(),
            logger=logger,
        )
        # Nothing is requested until the pipeline iterates.
        assert session.post_calls == []

        with mock.patch(_SESSION_FACTORY, return_value=session):
            batches = list(cast("Iterable[list[dict[str, Any]]]", response.items()))

        assert [len(batch) for batch in batches] == [2]
        assert isinstance(batches[0], list)
