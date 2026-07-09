from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.payfit import payfit
from products.warehouse_sources.backend.temporal.data_imports.sources.payfit.payfit import (
    PAGE_SIZE,
    PAYFIT_BASE_URL,
    PayFitInvalidTokenError,
    PayFitResumeConfig,
    PayFitRetryableError,
    check_schema_access,
    get_company_id,
    get_rows,
    payfit_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.payfit.settings import ENDPOINTS, PAYFIT_ENDPOINTS

# Call the undecorated functions so the tenacity retry/backoff wrappers don't slow failure-path tests.
_fetch_page_unwrapped = payfit._fetch_page.__wrapped__  # type: ignore[attr-defined]
_fetch_payslips_unwrapped = payfit._fetch_payslips.__wrapped__  # type: ignore[attr-defined]
_introspect_unwrapped = payfit._introspect.__wrapped__  # type: ignore[attr-defined]

COMPANY_ID = "company-1"


class _FakeResumableManager:
    def __init__(self, state: PayFitResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PayFitResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PayFitResumeConfig | None:
        return self._state

    def save_state(self, data: PayFitResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str | None, tuple[list[dict], str | None]],
        endpoint: str = "collaborators",
    ) -> list[dict]:
        def fake_fetch(
            session: Any,
            path: str,
            data_key: str,
            next_page_token: str | None,
            extra_params: dict,
            logger: Any,
        ) -> tuple[list[dict], str | None]:
            return pages[next_page_token]

        monkeypatch.setattr(payfit, "_fetch_page", fake_fetch)
        monkeypatch.setattr(payfit, "get_company_id", lambda session, api_key: COMPANY_ID)
        monkeypatch.setattr(payfit, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="payfit-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_page_without_token_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([{"id": "1"}, {"id": "2"}], None)})
        assert rows == [{"id": "1"}, {"id": "2"}]
        # No next page token, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_page_token_until_exhausted(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: dict[str | None, tuple[list[dict], str | None]] = {
            None: ([{"id": "1"}], "tok-2"),
            "tok-2": ([{"id": "2"}], None),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": "1"}, {"id": "2"}]
        # State is saved after the first page is yielded, then we stop on the final page.
        assert [s.next_page_token for s in manager.saved] == ["tok-2"]

    def test_resumes_from_saved_page_token(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PayFitResumeConfig(next_page_token="tok-99"))
        # The initial (token=None) page must never be fetched on resume.
        rows = self._collect(manager, monkeypatch, {"tok-99": ([{"id": "5"}], None)})
        assert rows == [{"id": "5"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {None: ([], None)})
        assert rows == []
        assert manager.saved == []


class TestGetPayslipRows:
    def test_fans_out_over_collaborator_pages_and_stamps_parent_id(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        collaborator_pages: dict[str | None, tuple[list[dict], str | None]] = {
            None: ([{"id": "collab-1"}, {"id": "collab-2"}], "tok-2"),
            "tok-2": ([{"id": "collab-3"}], None),
        }
        payslips_by_collaborator = {
            "collab-1": [{"payslipId": "p1", "collaboratorId": "collab-1"}],
            "collab-2": [],
            "collab-3": [{"payslipId": "p2", "collaboratorId": "collab-3"}],
        }

        def fake_fetch(
            session: Any,
            path: str,
            data_key: str,
            next_page_token: str | None,
            extra_params: dict,
            logger: Any,
        ) -> tuple[list[dict], str | None]:
            assert path == f"/companies/{COMPANY_ID}/collaborators"
            return collaborator_pages[next_page_token]

        def fake_payslips(session: Any, company_id: str, collaborator_id: str, logger: Any) -> list[dict]:
            assert company_id == COMPANY_ID
            return payslips_by_collaborator[collaborator_id]

        monkeypatch.setattr(payfit, "_fetch_page", fake_fetch)
        monkeypatch.setattr(payfit, "_fetch_payslips", fake_payslips)
        monkeypatch.setattr(payfit, "get_company_id", lambda session, api_key: COMPANY_ID)
        monkeypatch.setattr(payfit, "make_tracked_session", lambda **kwargs: MagicMock())

        batches = list(
            get_rows(
                api_key="payfit-key",
                endpoint="payslips",
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
        )

        # One batch per collaborators page; resume state tracks the collaborators cursor after each
        # yielded batch.
        assert batches == [
            [{"payslipId": "p1", "collaboratorId": "collab-1"}],
            [{"payslipId": "p2", "collaboratorId": "collab-3"}],
        ]
        assert [s.next_page_token for s in manager.saved] == ["tok-2"]


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
    _EMPTY = {"collaborators": [], "meta": {}}

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

    def test_first_page_sends_max_results_and_extra_params_without_token(self) -> None:
        session = self._session_returning(200, {"absences": [], "meta": {}})
        _fetch_page_unwrapped(session, "/companies/c/absences", "absences", None, {"status": "all"}, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"maxResults": PAGE_SIZE, "status": "all"}

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
    def test_returns_company_id_for_active_token(self) -> None:
        session = self._session_returning(200, {"active": True, "company_id": "company-1"})
        assert get_company_id(session, "payfit-key") == "company-1"
        args, kwargs = session.post.call_args
        assert args[0] == payfit.PAYFIT_INTROSPECT_URL
        assert kwargs["json"] == {"token": "payfit-key"}

    @parameterized.expand(
        [
            ("inactive_token", 200, {"active": False}),
            ("missing_company_id", 200, {"active": True}),
            ("unauthorized", 401, None),
            ("forbidden", 403, None),
        ]
    )
    def test_invalid_tokens_raise_non_retryable_error(self, _name: str, status: int, body: Any) -> None:
        session = self._session_returning(status, body)
        with pytest.raises(PayFitInvalidTokenError):
            get_company_id(session, "payfit-key")

    @parameterized.expand([("rate_limited", 429), ("server_error", 500)])
    def test_transient_statuses_are_retryable(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(PayFitRetryableError):
            _introspect_unwrapped(session, "payfit-key")


class TestValidateCredentials(_ResponseSessionMixin):
    @parameterized.expand(
        [
            ("active_with_company", 200, {"active": True, "company_id": "company-1"}, True, None),
            ("inactive", 200, {"active": False}, False, "Invalid PayFit API key"),
            ("no_company_id", 200, {"active": True}, False, "PayFit token introspection returned no company ID"),
            ("unauthorized", 401, None, False, "Invalid PayFit API key"),
            ("server_error", 500, None, False, "PayFit returned HTTP 500"),
        ]
    )
    @patch(f"{payfit.__name__}.make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        body: Any,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        mock_session.return_value = self._session_returning(status, body)
        assert validate_credentials("payfit-key") == (expected_valid, expected_message)

    @patch(f"{payfit.__name__}.make_tracked_session")
    def test_connection_error_maps_to_message(self, mock_session: MagicMock) -> None:
        session = MagicMock()
        session.post.side_effect = requests.ConnectionError("boom")
        mock_session.return_value = session
        valid, message = validate_credentials("payfit-key")
        assert valid is False
        assert message is not None and "boom" in message


class TestCheckSchemaAccess(_ResponseSessionMixin):
    @staticmethod
    def _session_with(introspect_body: dict, endpoint_status: int) -> MagicMock:
        session = MagicMock()
        session.post.return_value = _ResponseSessionMixin._response(200, introspect_body)
        session.get.return_value = _ResponseSessionMixin._response(endpoint_status, {})
        return session

    _ACTIVE = {"active": True, "company_id": "company-1"}

    @parameterized.expand(
        [
            ("reachable", 200, True),
            ("missing_scope", 403, False),
            ("bad_key", 401, False),
        ]
    )
    @patch(f"{payfit.__name__}.make_tracked_session")
    def test_endpoint_status_mapping(
        self, _name: str, endpoint_status: int, expected_valid: bool, mock_session: MagicMock
    ) -> None:
        mock_session.return_value = self._session_with(self._ACTIVE, endpoint_status)
        valid, _message = check_schema_access("payfit-key", "contracts")
        assert valid is expected_valid

    @patch(f"{payfit.__name__}.make_tracked_session")
    def test_missing_scope_message_names_the_scope(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session_with(self._ACTIVE, 403)
        valid, message = check_schema_access("payfit-key", "absences")
        assert valid is False
        assert message is not None and "time:read" in message

    @patch(f"{payfit.__name__}.make_tracked_session")
    def test_payslips_probe_uses_collaborators_dependency(self, mock_session: MagicMock) -> None:
        session = self._session_with(self._ACTIVE, 200)
        mock_session.return_value = session
        valid, _message = check_schema_access("payfit-key", "payslips")
        assert valid is True
        args, _ = session.get.call_args
        # Payslip paths need a collaborator id, so the scope probe targets the collaborators list.
        assert args[0] == f"{PAYFIT_BASE_URL}/companies/company-1/collaborators"

    @patch(f"{payfit.__name__}.make_tracked_session")
    def test_inactive_token_fails_before_probing(self, mock_session: MagicMock) -> None:
        session = self._session_with({"active": False}, 200)
        mock_session.return_value = session
        valid, message = check_schema_access("payfit-key", "contracts")
        assert valid is False
        assert message == "Invalid PayFit API key"
        session.get.assert_not_called()


class TestPayFitSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = payfit_source(
            api_key="payfit-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == PAYFIT_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp exists across the endpoints, so we don't partition.
        assert response.partition_mode is None

    def test_payslips_primary_key_includes_parent_id(self) -> None:
        # Payslip rows are aggregated across every collaborator, so the key must carry the parent id.
        assert PAYFIT_ENDPOINTS["payslips"].primary_keys == ["collaboratorId", "payslipId"]
