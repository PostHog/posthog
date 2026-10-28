from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.payfit import PayFitSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.payfit import payfit
from products.warehouse_sources.backend.temporal.data_imports.sources.payfit.payfit import (
    PAGE_SIZE,
    PAYFIT_BASE_URL,
    PayFitInvalidTokenError,
    PayFitResumeConfig,
    PayFitRetryableError,
    check_schema_access,
    get_company_id,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.payfit.settings import ENDPOINTS, PAYFIT_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.payfit.source import PayFitSource

# Call the undecorated functions so the tenacity retry/backoff wrappers don't slow failure-path tests.
_fetch_page_unwrapped = payfit._fetch_page.__wrapped__  # type: ignore[attr-defined]
_fetch_payslips_unwrapped = payfit._fetch_payslips.__wrapped__  # type: ignore[attr-defined]
_introspect_unwrapped = payfit._introspect.__wrapped__  # type: ignore[attr-defined]

COMPANY_ID = "company-1"


def _driver() -> SourceDriver:
    return SourceDriver(PayFitSource(), PayFitSourceConfig(api_key="payfit-key"))


def _introspection_response() -> ScriptedResponse:
    return ScriptedResponse(json={"active": True, "company_id": COMPANY_ID})


class TestGetRows:
    def test_follows_page_token_until_exhausted(self) -> None:
        result = _driver().run(
            "collaborators",
            [
                _introspection_response(),
                ScriptedResponse(json={"collaborators": [{"id": "1"}], "meta": {"nextPageToken": "tok-2"}}),
                ScriptedResponse(json={"collaborators": [{"id": "2"}], "meta": {"nextPageToken": None}}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "1"}, {"id": "2"}]
        assert result.params("maxResults") == [None, "50", "50"]
        assert result.params("nextPageToken") == [None, None, "tok-2"]
        # State is saved after the first page is yielded, then we stop on the final page.
        assert result.saved_states == [PayFitResumeConfig(next_page_token="tok-2")]
        assert result.committed_states == [PayFitResumeConfig(next_page_token="tok-2")]

    def test_resumes_from_saved_page_token(self) -> None:
        # The initial (token=None) page must never be fetched on resume.
        result = _driver().run(
            "collaborators",
            [
                _introspection_response(),
                ScriptedResponse(json={"collaborators": [{"id": "5"}], "meta": {}}),
            ],
            resume_state=PayFitResumeConfig(next_page_token="tok-99"),
        )

        assert result.raised is None
        assert result.rows == [{"id": "5"}]
        assert result.params("nextPageToken") == [None, "tok-99"]


class TestGetPayslipRows:
    def test_fans_out_over_collaborator_pages_and_stamps_parent_id(self) -> None:
        result = _driver().run(
            "payslips",
            [
                _introspection_response(),
                ScriptedResponse(
                    json={
                        "collaborators": [{"id": "collab-1"}, {"id": "collab-2"}],
                        "meta": {"nextPageToken": "tok-2"},
                    }
                ),
                ScriptedResponse(json={"payslips": [{"payslipId": "p1"}]}),
                ScriptedResponse(json={"payslips": []}),
                ScriptedResponse(json={"collaborators": [{"id": "collab-3"}], "meta": {}}),
                ScriptedResponse(json={"payslips": [{"payslipId": "p2"}]}),
            ],
        )

        # One batch per collaborators page; resume state tracks the collaborators cursor after each
        # yielded batch.
        assert result.raised is None
        assert result.items == [
            [{"payslipId": "p1", "collaboratorId": "collab-1"}],
            [{"payslipId": "p2", "collaboratorId": "collab-3"}],
        ]
        assert result.paths == [
            "/introspect",
            f"/companies/{COMPANY_ID}/collaborators",
            f"/companies/{COMPANY_ID}/collaborators/collab-1/payslips",
            f"/companies/{COMPANY_ID}/collaborators/collab-2/payslips",
            f"/companies/{COMPANY_ID}/collaborators",
            f"/companies/{COMPANY_ID}/collaborators/collab-3/payslips",
        ]
        assert result.params("nextPageToken") == [None, None, None, None, "tok-2", None]
        assert result.saved_states == [PayFitResumeConfig(next_page_token="tok-2")]
        assert result.committed_states == [PayFitResumeConfig(next_page_token="tok-2")]


class _ResponseSessionMixin:
    @staticmethod
    def _response(status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        return response

    @classmethod
    def _session_returning(cls, status_code: int, body: Any = None) -> MagicMock:
        session = MagicMock()
        session.get.return_value = cls._response(status_code, body)
        session.post.return_value = cls._response(status_code, body)
        return session


class TestFetchPage(_ResponseSessionMixin):
    _EMPTY: dict[str, Any] = {"collaborators": [], "meta": {}}

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(PayFitRetryableError):
            _fetch_page_unwrapped(session, "/companies/c/collaborators", "collaborators", None, {}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/companies/c/collaborators", "collaborators", None, {}, MagicMock())

    @parameterized.expand(
        [
            ("next_token_present", {"collaborators": [{"id": "1"}], "meta": {"nextPageToken": "tok"}}, "tok"),
            ("next_token_null", {"collaborators": [{"id": "1"}], "meta": {"nextPageToken": None}}, None),
            ("meta_missing", {"collaborators": [{"id": "1"}]}, None),
        ]
    )
    def test_success_returns_rows_and_next_token(self, _name: str, body: dict, expected_token: str | None) -> None:
        session = self._session_returning(200, body)
        rows, next_token = _fetch_page_unwrapped(
            session, "/companies/c/collaborators", "collaborators", None, {}, MagicMock()
        )
        assert rows == [{"id": "1"}]
        assert next_token == expected_token

    @parameterized.expand([("non_dict", [{"id": "1"}]), ("missing_data_key", {"meta": {}})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(PayFitRetryableError):
            _fetch_page_unwrapped(session, "/companies/c/collaborators", "collaborators", None, {}, MagicMock())

    def test_subsequent_page_sends_next_page_token(self) -> None:
        session = self._session_returning(200, self._EMPTY)
        _fetch_page_unwrapped(session, "/companies/c/collaborators", "collaborators", "tok-42", {}, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"maxResults": PAGE_SIZE, "nextPageToken": "tok-42"}


class TestFetchPayslips(_ResponseSessionMixin):
    def test_stamps_collaborator_id_onto_rows(self) -> None:
        body = {"payslips": [{"payslipId": "p1", "year": "2026", "month": "01"}]}
        session = self._session_returning(200, body)
        rows = _fetch_payslips_unwrapped(session, "company-1", "collab-1", MagicMock())
        assert rows == [{"payslipId": "p1", "year": "2026", "month": "01", "collaboratorId": "collab-1"}]
        args, _ = session.get.call_args
        assert args[0] == f"{PAYFIT_BASE_URL}/companies/company-1/collaborators/collab-1/payslips"

    def test_unexpected_payload_is_retryable(self) -> None:
        session = self._session_returning(200, {"nope": []})
        with pytest.raises(PayFitRetryableError):
            _fetch_payslips_unwrapped(session, "company-1", "collab-1", MagicMock())


class TestGetCompanyId(_ResponseSessionMixin):
    @parameterized.expand(
        [
            ("inactive_token", 200, {"active": False}),
            ("missing_company_id", 200, {"active": True}),
            ("unauthorized", 401, None),
            ("forbidden", 403, None),
        ]
    )
    def test_invalid_tokens_raise_non_retryable_error(self, _name: str, status: int, body: Any) -> None:
        with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
            with pytest.raises(PayFitInvalidTokenError):
                get_company_id("payfit-key")

        assert [request.path for request in network.requests_log] == ["/introspect"]
        assert network.requests_log[0].json() == {"token": "payfit-key"}

    @parameterized.expand([("rate_limited", 429), ("server_error", 500)])
    def test_transient_statuses_are_retryable(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(PayFitRetryableError):
            _introspect_unwrapped(session, "payfit-key")


class TestValidateCredentials:
    # Status-code handling (401/403, 429/5xx retries, malformed payloads) lives in `_introspect`
    # and is covered by TestGetCompanyId; validation shares that path, so here we only assert the
    # claims-to-verdict mapping and that introspection failures surface as a message, not a raise.
    @parameterized.expand(
        [
            ("active_with_company", {"active": True, "company_id": "company-1"}, True, None),
            ("inactive", {"active": False}, False, "Invalid PayFit API key"),
            ("no_company_id", {"active": True}, False, "PayFit token introspection returned no company ID"),
        ]
    )
    def test_claims_mapping(
        self,
        _name: str,
        claims: dict,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network([ScriptedResponse(json=claims)]) as network:
            assert validate_credentials("payfit-key") == (expected_valid, expected_message)

        assert [request.path for request in network.requests_log] == ["/introspect"]
        assert network.requests_log[0].json() == {"token": "payfit-key"}
        assert network.session_options[0]["capture"] is False
        assert network.session_options[0]["allow_redirects"] is False
        assert network.session_options[0]["redact_values"] == ("payfit-key",)

    @parameterized.expand(
        [
            ("exhausted_retries", ScriptedResponse(status=500), "500"),
        ]
    )
    def test_introspection_failure_maps_to_message(
        self, _name: str, answer: ScriptedResponse | requests.ConnectionError, expected_fragment: str
    ) -> None:
        with scripted_network(always(answer)) as network:
            valid, message = validate_credentials("payfit-key")

        assert valid is False
        assert message is not None and expected_fragment in message
        assert {request.path for request in network.requests_log} == {"/introspect"}


class TestCheckSchemaAccess:
    @parameterized.expand(
        [
            ("reachable", 200, True),
            ("missing_scope", 403, False),
            ("bad_key", 401, False),
        ]
    )
    def test_endpoint_status_mapping(self, _name: str, endpoint_status: int, expected_valid: bool) -> None:
        with scripted_network(
            [_introspection_response(), ScriptedResponse(status=endpoint_status, json={})]
        ) as network:
            valid, _message = check_schema_access("payfit-key", "contracts")

        assert valid is expected_valid
        assert [request.path for request in network.requests_log] == [
            "/introspect",
            f"/companies/{COMPANY_ID}/contracts",
        ]
        assert network.requests_log[1].param("maxResults") == "1"

    def test_payslips_probe_uses_collaborators_dependency(self) -> None:
        with scripted_network([_introspection_response(), ScriptedResponse(json={})]) as network:
            valid, _message = check_schema_access("payfit-key", "payslips")

        assert valid is True
        # Payslip paths need a collaborator id, so the scope probe targets the collaborators list.
        assert network.requests_log[1].url == f"{PAYFIT_BASE_URL}/companies/{COMPANY_ID}/collaborators?maxResults=1"

    def test_inactive_token_fails_before_probing(self) -> None:
        with scripted_network([ScriptedResponse(json={"active": False})]) as network:
            valid, message = check_schema_access("payfit-key", "contracts")

        assert valid is False
        assert message == "Invalid PayFit API key"
        assert [request.path for request in network.requests_log] == ["/introspect"]


class TestPayFitSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        data_key = "collaborators" if endpoint == "payslips" else PAYFIT_ENDPOINTS[endpoint].data_key
        result = _driver().run(
            endpoint,
            [_introspection_response(), ScriptedResponse(json={data_key: [], "meta": {}})],
        )

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == PAYFIT_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp exists across the endpoints, so we don't partition.
        assert response.partition_mode is None

    def test_payslips_primary_key_includes_parent_id(self) -> None:
        # Payslip rows are aggregated across every collaborator, so the key must carry the parent id.
        assert PAYFIT_ENDPOINTS["payslips"].primary_keys == ["collaboratorId", "payslipId"]
