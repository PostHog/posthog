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


class TestRows:
    @pytest.mark.parametrize("endpoint", ["advertisable_reports", "campaign_reports", "ad_reports"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_report_endpoints_filter_by_advertisables_in_entity_format(self, MockSession, endpoint):
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"eid": "ADV1"}]),
                _response([{"eid": "C1", "impressions": 5}]),
            ],
        )

        rows = _rows(_source(endpoint))

        assert rows == [{"eid": "C1", "impressions": 5, "_advertisable_eid": "ADV1"}]
        assert urlparse(snapshots[1]["url"]).path == ADROLL_ENDPOINTS[endpoint].path
        # The reporting endpoints take a list of advertisables, not a single one.
        assert parse_qs(urlparse(snapshots[1]["url"]).query)["advertisables"] == ["ADV1"]
        assert snapshots[1]["params"]["data_format"] == "entity"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_advertisables_without_eid_are_skipped(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"name": "broken"}])])

        assert _rows(_source("ads")) == []
        assert session.send.call_count == 1

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
