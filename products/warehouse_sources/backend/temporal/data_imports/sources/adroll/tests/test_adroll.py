import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.adroll import (
    MAX_RETRY_ATTEMPTS,
    AdRollResumeConfig,
    adroll_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.settings import ADROLL_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the adroll module.
ADROLL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.adroll.adroll.make_tracked_session"
)

CAMPAIGNS_PATH = ADROLL_ENDPOINTS["campaigns"].path
ADS_PATH = ADROLL_ENDPOINTS["ads"].path


def _response(results: list[dict[str, Any]] | None, *, drop_results: bool = False, status_code: int = 200) -> Response:
    body: dict[str, Any] = {}
    if not drop_results:
        body["results"] = results or []
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _error_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = b'{"error": "boom"}'
    return resp


def _make_manager(resume_state: AdRollResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return snapshots of each request AT PREPARE TIME.

    ``request.params`` dicts can be mutated/rebuilt across requests, so snapshot a copy
    when each request is prepared instead of inspecting after the run.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock | None = None):
    return adroll_source(
        client_id="cid",
        personal_access_token="pat",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
    )


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(ADROLL_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        assert validate_credentials("cid", "pat") is expected

    @mock.patch(ADROLL_SESSION_PATCH)
    def test_validate_includes_apikey_and_token_header(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("cid", "pat")

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["apikey"] == ["cid"]
        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Token pat"

    @mock.patch(ADROLL_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("cid", "pat") is False


class TestRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_advertisables_single_fetch(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"eid": "ADV1"}])])

        rows = _rows(_source("advertisables"))

        assert rows == [{"eid": "ADV1"}]
        assert session.send.call_count == 1
        assert urlparse(snapshots[0]["url"]).path == "/api/v1/organization/get_advertisables"
        assert snapshots[0]["params"]["apikey"] == "cid"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_requests_carry_token_auth_header(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"eid": "ADV1"}])])

        _rows(_source("advertisables"))

        auth = snapshots[0]["auth"]
        prepared = mock.MagicMock(headers={})
        auth(prepared)
        assert prepared.headers["Authorization"] == "Token pat"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_campaigns_fan_out_over_advertisables(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"eid": "ADV1"}, {"eid": "ADV2"}]),
                _response([{"eid": "C1"}]),
                _response([{"eid": "C2"}]),
            ],
        )

        rows = _rows(_source("campaigns"))

        assert [(c["eid"], c["_advertisable_eid"]) for c in rows] == [("C1", "ADV1"), ("C2", "ADV2")]
        child_queries = [parse_qs(urlparse(s["url"]).query) for s in snapshots[1:]]
        assert child_queries[0]["advertisable"] == ["ADV1"]
        assert child_queries[1]["advertisable"] == ["ADV2"]
        assert all(urlparse(s["url"]).path == CAMPAIGNS_PATH for s in snapshots[1:])
        # The apikey param rides along on every request, parent and children alike.
        assert all(s["params"]["apikey"] == "cid" for s in snapshots)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_advertisables_without_eid_are_skipped(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"name": "broken"}])])

        assert _rows(_source("ads")) == []
        assert session.send.call_count == 1

    @pytest.mark.parametrize("endpoint", ["advertisables", "campaigns"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_nothing(self, MockSession, endpoint):
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _rows(_source(endpoint)) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_results_key_is_tolerated(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response(None, drop_results=True)])

        assert _rows(_source("advertisables")) == []

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_retryable_status_then_succeeds(self, MockSession, _mock_sleep):
        session = MockSession.return_value
        _wire(
            session,
            [
                _error_response(500),
                _error_response(429),
                _response([{"eid": "ADV1"}]),
            ],
        )

        rows = _rows(_source("advertisables"))

        assert rows == [{"eid": "ADV1"}]
        assert session.send.call_count == MAX_RETRY_ATTEMPTS

    @mock.patch("time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_exhausted_raises(self, MockSession, _mock_sleep):
        session = MockSession.return_value
        _wire(session, [_error_response(500)] * MAX_RETRY_ATTEMPTS)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("advertisables"))

        assert session.send.call_count == MAX_RETRY_ATTEMPTS

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_retryable_client_error_raises(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_error_response(401)])

        with pytest.raises(Exception, match="401"):
            _rows(_source("advertisables"))

        assert session.send.call_count == 1


class TestFanOutResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_completed_advertisables(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"eid": "ADV1"}, {"eid": "ADV2"}]),
                _response([{"eid": "C1"}]),
                _response([{"eid": "C2"}]),
            ],
        )

        manager = _make_manager()
        _rows(_source("campaigns", manager))

        final_state = manager.save_state.call_args.args[0]
        assert final_state == AdRollResumeConfig(
            fanout_state={
                "completed": [
                    f"{CAMPAIGNS_PATH}?advertisable=ADV1",
                    f"{CAMPAIGNS_PATH}?advertisable=ADV2",
                ],
                "current": None,
                "child_state": None,
            }
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_advertisables(self, MockSession):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"eid": "ADV1"}, {"eid": "ADV2"}]),
                _response([{"eid": "C2"}]),
            ],
        )

        manager = _make_manager(
            AdRollResumeConfig(
                fanout_state={
                    "completed": [f"{CAMPAIGNS_PATH}?advertisable=ADV1"],
                    "current": None,
                    "child_state": None,
                }
            )
        )
        rows = _rows(_source("campaigns", manager))

        # ADV1 was already synced — only the parent list and ADV2's campaigns are fetched.
        assert [(c["eid"], c["_advertisable_eid"]) for c in rows] == [("C2", "ADV2")]
        assert session.send.call_count == 2
        assert parse_qs(urlparse(snapshots[1]["url"]).query)["advertisable"] == ["ADV2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_resume_state_saved_for_plain_endpoint(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"eid": "ADV1"}])])

        manager = _make_manager()
        _rows(_source("advertisables", manager))

        manager.save_state.assert_not_called()


class TestAdRollSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = ADROLL_ENDPOINTS[endpoint]
        response = _source(endpoint)

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
