import datetime as dt
from collections.abc import Iterable
from typing import Any, Optional, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import jwt
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
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.settings import DOCUSIGN_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.tests.conftest import (
    PRIVATE_KEY_PEM,
    PUBLIC_KEY_PEM,
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

EXPECTED_BASE_URL = "https://na3.docusign.net/restapi/v2.1/accounts/222"


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
    def test_jwt_assertion_carries_the_claims_docusign_requires(self) -> None:
        session = FakeSession(post_responses=[FakeResponse(200, TOKEN_PAYLOAD)])

        token = mint_access_token(session.as_session(), jwt_credentials())

        assert token == "tok-1"
        url, kwargs = session.post_calls[0]
        assert url == "https://account.docusign.com/oauth/token"
        assert kwargs["data"]["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"

        claims = jwt.decode(
            kwargs["data"]["assertion"],
            PUBLIC_KEY_PEM,
            algorithms=["RS256"],
            audience="account.docusign.com",
        )
        assert claims["iss"] == "int-key"
        assert claims["sub"] == "user-guid"
        assert claims["scope"] == "signature impersonation"
        assert claims["exp"] > claims["iat"]

    def test_demo_environment_signs_against_the_demo_auth_host(self) -> None:
        session = FakeSession(post_responses=[FakeResponse(200, TOKEN_PAYLOAD)])

        mint_access_token(session.as_session(), jwt_credentials(environment="demo"))

        url, kwargs = session.post_calls[0]
        assert url == "https://account-d.docusign.com/oauth/token"
        claims = jwt.decode(
            kwargs["data"]["assertion"],
            PUBLIC_KEY_PEM,
            algorithms=["RS256"],
            audience="account-d.docusign.com",
        )
        assert claims["iss"] == "int-key"

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

    def test_resolve_account_defaults_to_the_users_default_account(self) -> None:
        session = FakeSession(get_responses=[FakeResponse(200, USERINFO_PAYLOAD)])

        account = resolve_account(session.as_session(), jwt_credentials(), "tok-1")

        assert account.account_id == "222"
        # Trailing slash on base_uri must not double up in the built URL.
        assert account.base_url == EXPECTED_BASE_URL
        assert session.get_calls[0][1]["headers"]["Authorization"] == "Bearer tok-1"

    def test_resolve_account_honors_an_explicitly_configured_account(self) -> None:
        session = FakeSession(get_responses=[FakeResponse(200, USERINFO_PAYLOAD)])

        account = resolve_account(session.as_session(), jwt_credentials(account_id="111"), "tok-1")

        assert account.base_url == "https://na2.docusign.net/restapi/v2.1/accounts/111"

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

    def test_pagination_follows_next_uri_and_advances_start_position(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[
                FakeResponse(200, USERINFO_PAYLOAD),
                FakeResponse(200, envelope_page(PAGE_SIZE, offset=0, next_uri="/restapi/next")),
                FakeResponse(200, envelope_page(3, offset=PAGE_SIZE)),
            ],
        )

        batches, manager = run_rows(session, jwt_credentials(), "envelopes", logger)

        assert [len(batch) for batch in batches] == [PAGE_SIZE, 3]
        positions = [
            parse_qs(urlparse(url).query)["start_position"][0] for url, _ in session.get_calls if "/envelopes" in url
        ]
        assert positions == ["0", str(PAGE_SIZE)]
        # Checkpoint written after the first page was yielded, then dropped once the walk finished.
        assert [state.start_position for state in manager.saved] == [PAGE_SIZE]
        assert manager.cleared is True

    def test_pagination_stops_on_a_short_page_without_next_uri(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[FakeResponse(200, USERINFO_PAYLOAD), FakeResponse(200, envelope_page(2))],
        )

        batches, manager = run_rows(session, jwt_credentials(), "envelopes", logger)

        assert len(batches) == 1
        assert manager.saved == []

    def test_unpaginated_endpoint_is_requested_once_even_on_a_full_page(self, logger: FilteringBoundLogger) -> None:
        folders = {"folders": [{"folderId": str(i), "name": f"f{i}"} for i in range(PAGE_SIZE)]}
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[FakeResponse(200, USERINFO_PAYLOAD), FakeResponse(200, folders)],
        )

        batches, _ = run_rows(session, jwt_credentials(), "folders", logger)

        assert len(batches) == 1
        assert len([url for url, _ in session.get_calls if "/folders" in url]) == 1

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

    def test_incremental_watermark_becomes_the_from_date_filter(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[FakeResponse(200, USERINFO_PAYLOAD), FakeResponse(200, envelope_page(1))],
        )

        run_rows(
            session,
            jwt_credentials(),
            "envelopes",
            logger,
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.datetime(2024, 5, 1, 12, 30, tzinfo=dt.UTC),
        )

        query = parse_qs(urlparse(next(url for url, _ in session.get_calls if "/envelopes" in url)).query)
        assert query["from_date"] == ["2024-05-01T12:30:00Z"]
        assert query["order_by"] == ["status_changed"]
        assert query["order"] == ["asc"]

    def test_full_refresh_falls_back_to_the_configured_start_date(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[FakeResponse(200, USERINFO_PAYLOAD), FakeResponse(200, envelope_page(1))],
        )

        run_rows(session, jwt_credentials(), "envelopes", logger, start_date="2021-01-01T00:00:00Z")

        query = parse_qs(urlparse(next(url for url, _ in session.get_calls if "/envelopes" in url)).query)
        assert query["from_date"] == ["2021-01-01T00:00:00Z"]

    def test_endpoint_without_a_date_filter_sends_no_from_date(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[FakeResponse(200, USERINFO_PAYLOAD), FakeResponse(200, {"users": [{"userId": "u1"}]})],
        )

        run_rows(
            session,
            jwt_credentials(),
            "users",
            logger,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )

        query = parse_qs(urlparse(next(url for url, _ in session.get_calls if "/users" in url)).query)
        assert "from_date" not in query

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

    @pytest.mark.parametrize("endpoint_name", sorted(DOCUSIGN_ENDPOINTS))
    def test_source_response_matches_the_endpoint_catalog(
        self, endpoint_name: str, logger: FilteringBoundLogger
    ) -> None:
        endpoint = DOCUSIGN_ENDPOINTS[endpoint_name]

        response = docusign_source(
            credentials=jwt_credentials(),
            endpoint_name=endpoint_name,
            start_date=None,
            resumable_source_manager=FakeResumeManager(),
            logger=logger,
        )

        assert response.name == endpoint_name
        assert response.primary_keys == endpoint.primary_key
        assert response.sort_mode == "asc"
        if endpoint.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [endpoint.partition_key]
        else:
            assert response.partition_keys is None

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
