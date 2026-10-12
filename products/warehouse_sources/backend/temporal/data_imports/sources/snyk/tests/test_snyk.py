import json
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.snyk import (
    SNYK_REST_VERSION,
    SnykResumeConfig,
    _next_page_url,
    snyk_source,
    validate_credentials,
)

HOST = "https://api.snyk.io"

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the snyk module.
SNYK_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.snyk.snyk.make_tracked_session"


def _response(body: Any, *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode() if body is not None else b""
    return resp


def _list_body(items: list[dict], next_link: Any = None) -> dict:
    body: dict[str, Any] = {"data": items}
    if next_link is not None:
        body["links"] = {"next": next_link}
    return body


def _make_manager(resume: SnykResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session; capture each request's URL and params AT PREPARE TIME.

    ``request.params`` is a dict mutated in place across pages, so snapshot a copy per request. The
    prepared object must expose a real ``.url`` because the client host-pins every request URL.
    """
    session.headers = {}
    urls: list[str] = []
    params: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        urls.append(request.url)
        params.append(dict(request.params or {}))
        prepared = MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return urls, params


def _source(endpoint: str, manager: MagicMock, **kwargs: Any) -> Any:
    return snyk_source(
        region=kwargs.pop("region", "us"),
        api_token=kwargs.pop("api_token", "tok"),
        organization_id=kwargs.pop("organization_id", None),
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        should_use_incremental_field=kwargs.pop("should_use_incremental_field", False),
        db_incremental_field_last_value=kwargs.pop("db_incremental_field_last_value", None),
        incremental_field=kwargs.pop("incremental_field", None),
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestNextPageUrl:
    @parameterized.expand(
        [
            (
                "absolute_same_host",
                {"links": {"next": f"{HOST}/rest/orgs?starting_after=abc"}},
                f"{HOST}/rest/orgs?starting_after=abc",
            ),
            ("absolute_other_host_rejected", {"links": {"next": "https://evil.example.com/rest/orgs"}}, None),
            ("http_scheme_rejected", {"links": {"next": "http://api.snyk.io/rest/orgs?x=1"}}, None),
            (
                "relative_with_rest_prefix",
                {"links": {"next": "/rest/orgs?starting_after=abc"}},
                f"{HOST}/rest/orgs?starting_after=abc",
            ),
            (
                "relative_without_rest_prefix",
                {"links": {"next": "/orgs/o1/issues?starting_after=abc"}},
                f"{HOST}/rest/orgs/o1/issues?starting_after=abc",
            ),
            (
                "relative_without_leading_slash",
                {"links": {"next": "orgs?starting_after=abc"}},
                f"{HOST}/rest/orgs?starting_after=abc",
            ),
            (
                "href_object_form",
                {"links": {"next": {"href": "/rest/orgs?starting_after=abc"}}},
                f"{HOST}/rest/orgs?starting_after=abc",
            ),
            ("no_next", {"links": {"prev": "/rest/orgs"}}, None),
            ("empty_next", {"links": {"next": ""}}, None),
            ("no_links", {"data": []}, None),
            ("non_dict_payload", [], None),
        ]
    )
    def test_next_page_url(self, _name: str, payload: Any, expected: str | None) -> None:
        assert _next_page_url(HOST, payload) == expected


class TestRetryClassification:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_without_retry(self, MockSession: MagicMock) -> None:
        # 401 is a permanent auth failure — surfaced immediately as an HTTPError, no retry.
        session = MockSession.return_value
        _wire(session, [_response({"errors": [{"status": "401"}]}, status=401)])
        with pytest.raises(HTTPError):
            _rows(_source("organizations", _make_manager()))
        assert session.send.call_count == 1


class TestTopLevelOrganizations:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yield_and_resumes_from_it(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        page2 = f"{HOST}/rest/orgs?version={SNYK_REST_VERSION}&limit=100&starting_after=cursor"
        _wire(session, [_response(_list_body([{"id": "o1"}], next_link=page2)), _response(_list_body([{"id": "o2"}]))])
        manager = _make_manager()
        _rows(_source("organizations", manager))
        # Checkpoint saved after the first (full) page, pointing at the next-page URL.
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert any(s.next_url == page2 for s in saved)

        # A resumed run seeds the request from the saved next URL.
        resume_session = MockSession.return_value
        urls, _params = _wire(resume_session, [_response(_list_body([{"id": "o2"}]))])
        rows = _rows(_source("organizations", _make_manager(SnykResumeConfig(next_url=page2))))
        assert rows == [{"id": "o2"}]
        assert urls[0] == page2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_state_on_wrong_host_is_rejected(self, MockSession: MagicMock) -> None:
        # The resume URL is fetched with the auth header attached, so tampered state must not be
        # able to redirect the request off the Snyk host.
        session = MockSession.return_value
        _wire(session, [])
        with pytest.raises(ValueError):
            _rows(
                _source("organizations", _make_manager(SnykResumeConfig(next_url="https://evil.example.com/rest/orgs")))
            )
        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_configured_org_fetches_single_org_directly(self, MockSession: MagicMock) -> None:
        # A single-org connection must not enumerate every org: it fetches /orgs/{org_id} directly
        # and emits only that org.
        session = MockSession.return_value
        urls, _params = _wire(
            session, [_response({"data": {"id": "o9", "type": "org", "attributes": {"name": "Org 9"}}})]
        )
        rows = _rows(_source("organizations", _make_manager(), organization_id="o9"))
        assert rows == [{"id": "o9", "type": "org", "name": "Org 9"}]
        assert urls == [f"{HOST}/rest/orgs/o9"]

    def test_configured_org_id_is_validated_before_the_request(self) -> None:
        # The org id is interpolated into the URL path, so a path-altering value must be rejected
        # up front — before any resource is built or request made.
        with pytest.raises(ValueError):
            _source("organizations", _make_manager(), organization_id="../self")


class TestPerOrgFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_every_org_and_injects_organization_id(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(_list_body([{"id": "o1"}, {"id": "o2"}])),
                _response(_list_body([{"id": "i1", "attributes": {"title": "a"}}])),
                _response(_list_body([{"id": "i2", "attributes": {"title": "b"}}])),
            ],
        )
        rows = _rows(_source("issues", _make_manager()))
        assert rows == [
            {"id": "i1", "title": "a", "organization_id": "o1"},
            {"id": "i2", "title": "b", "organization_id": "o2"},
        ]

    def test_invalid_configured_org_id_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            _source("issues", _make_manager(), organization_id="../self")


class TestIncrementalFilters:
    @parameterized.expand(
        [
            ("default_field", None, "updated_after"),
            ("explicit_updated_at", "updated_at", "updated_after"),
            ("created_at_maps_to_created_after", "created_at", "created_after"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_watermark_becomes_server_side_filter(
        self, _name: str, incremental_field: str | None, param: str, MockSession: MagicMock
    ) -> None:
        from datetime import UTC, datetime

        session = MockSession.return_value
        _urls, params = _wire(session, [_response(_list_body([{"id": "i1"}]))])
        rows = _rows(
            _source(
                "issues",
                _make_manager(),
                organization_id="o1",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field=incremental_field,
            )
        )
        assert rows == [{"id": "i1", "organization_id": "o1"}]
        assert params[0][param] == "2026-01-01T00:00:00Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_sync_has_no_filter(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _urls, params = _wire(session, [_response(_list_body([{"id": "i1"}]))])
        rows = _rows(
            _source(
                "issues",
                _make_manager(),
                organization_id="o1",
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
            )
        )
        assert rows == [{"id": "i1", "organization_id": "o1"}]
        assert "updated_after" not in params[0]
        assert "created_after" not in params[0]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    @mock.patch(SNYK_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool, mock_session: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        mock_session.return_value = session
        ok, _error = validate_credentials("us", "tok")
        assert ok is expected_ok
        # The probe must carry the mandatory dated version param or Snyk rejects the call.
        assert session.get.call_args.args[0] == f"{HOST}/rest/self?version={SNYK_REST_VERSION}"

    @mock.patch(SNYK_SESSION_PATCH)
    def test_configured_org_is_probed_on_the_selected_region(self, mock_session: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=200)
        mock_session.return_value = session
        ok, _error = validate_credentials("eu", "tok", "org-uuid-1")
        assert ok is True
        assert (
            session.get.call_args.args[0] == f"https://api.eu.snyk.io/rest/orgs/org-uuid-1?version={SNYK_REST_VERSION}"
        )

    def test_invalid_org_id_fails_without_a_request(self) -> None:
        with mock.patch(SNYK_SESSION_PATCH) as mock_session:
            ok, error = validate_credentials("us", "tok", "../../self")
        assert ok is False
        assert error is not None
        mock_session.assert_not_called()

    @mock.patch(SNYK_SESSION_PATCH)
    def test_request_exception_is_failure(self, mock_session: MagicMock) -> None:
        import requests

        session = MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError("boom")
        mock_session.return_value = session
        ok, error = validate_credentials("us", "tok")
        assert ok is False
        assert error is not None


class TestTokenRedaction:
    """The token rides in a custom `Authorization: token …` scheme; every tracked session built for
    Snyk must redact it by value so it can't leak into logs or error messages."""

    @mock.patch(SNYK_SESSION_PATCH)
    def test_validate_credentials_redacts_token(self, mock_session: MagicMock) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=200)
        mock_session.return_value = session
        validate_credentials("us", "super-secret-token")
        assert mock_session.call_args.kwargs.get("redact_values") == ("super-secret-token",)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_redacts_token(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_list_body([{"id": "o1"}]))])
        _rows(_source("organizations", _make_manager(), api_token="super-secret-token"))
        # The framework derives the redaction set from the auth's secret values; the token is
        # carried inside the `token <token>` api-key value.
        redact_values = MockSession.call_args.kwargs.get("redact_values") or ()
        assert any("super-secret-token" in value for value in redact_values)
