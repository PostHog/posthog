import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from requests import PreparedRequest, Response
from requests.structures import CaseInsensitiveDict

from products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.propertyware import (
    PAGE_SIZE,
    PropertywareAuth,
    PropertywareResumeConfig,
    _format_pw_datetime,
    propertyware_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the propertyware module.
PROPERTYWARE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.propertyware.make_tracked_session"
)

_PINNED_URL = "https://api.propertyware.com/pw/api/rest/v1/portfolios"


def _response(items: list[dict[str, Any]] | None, *, status: int = 200, raw: Optional[bytes] = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = _PINNED_URL
    resp.reason = "OK" if status < 400 else "Unauthorized"
    resp._content = raw if raw is not None else json.dumps(items or []).encode()
    return resp


def _make_manager(resume_state: PropertywareResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME."""
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock(url=_PINNED_URL)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, **kwargs: Any):
    return propertyware_source(
        kwargs.pop("client_id", "cid"),
        kwargs.pop("client_secret", "secret"),
        kwargs.pop("system_id", "org-1"),
        kwargs.pop("endpoint", "Portfolios"),
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestPropertywareAuth:
    def test_sets_all_three_headers(self) -> None:
        auth = PropertywareAuth(client_id="cid", client_secret="csecret", system_id="org-1")
        request = PreparedRequest()
        request.headers = CaseInsensitiveDict()
        auth(request)
        assert request.headers["x-propertyware-client-id"] == "cid"
        assert request.headers["x-propertyware-client-secret"] == "csecret"
        assert request.headers["x-propertyware-system-id"] == "org-1"

    def test_secret_values_redacts_all_three(self) -> None:
        auth = PropertywareAuth(client_id="cid", client_secret="csecret", system_id="org-1")
        assert set(auth.secret_values()) == {"cid", "csecret", "org-1"}

    def test_secret_values_omits_blank_fields(self) -> None:
        auth = PropertywareAuth(client_id="cid", client_secret="", system_id="")
        assert auth.secret_values() == ("cid",)


class TestFormatPwDatetime:
    def test_date_formats_at_midnight(self) -> None:
        assert _format_pw_datetime(date(2021, 6, 7)) == "2021-06-07T00:00:00Z"

    def test_string_passes_through(self) -> None:
        assert _format_pw_datetime("2022-03-04T05:06:07Z") == "2022-03-04T05:06:07Z"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sync_requests_pin_host_and_refuse_redirects(self, MockSession) -> None:
        # Credentials ride in custom headers, not `Authorization` — `requests` won't strip those
        # on a cross-origin redirect, so every sync request (not just the validation probe) must
        # refuse to follow one and stay pinned to the Propertyware host.
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        _rows(_source(_make_manager()))

        assert session.send.call_args.kwargs["allow_redirects"] is False

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 7}])])

        rows = _rows(_source(_make_manager(PropertywareResumeConfig(offset=1000))))

        assert rows == [{"id": 7}]
        assert params[0]["offset"] == 1000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_applied_on_every_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(full_page), _response([])])

        _rows(
            _source(
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2020, 1, 1, tzinfo=UTC),
            )
        )
        assert all(p.get("lastModifiedDateTimeStart") == "2020-01-01T00:00:00Z" for p in params)
        assert len(params) == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_on_non_retryable_error(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status=401)])

        with pytest.raises(Exception, match="401 Client Error"):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_on_non_list_response(self, MockSession) -> None:
        session = MockSession.return_value
        # A 200 with an unexpected (non-array) body must fail loudly, not sync zero rows silently.
        _wire(session, [_response(None, raw=json.dumps({"error": "boom"}).encode())])

        with pytest.raises(ValueError, match="list response body"):
            _rows(_source(_make_manager()))


class TestValidateCredentials:
    @mock.patch(PROPERTYWARE_SESSION_PATCH)
    def test_probes_a_specific_endpoint_path(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("cid", "secret", "org-1", path="/leases?limit=1")
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == "https://api.propertyware.com/pw/api/rest/v1/leases?limit=1"
