import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.chameleon import (
    ChameleonResumeConfig,
    chameleon_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.settings import CHAMELEON_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the chameleon module.
CHAMELEON_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.chameleon.make_tracked_session"
)


def _response(body: dict[str, Any], status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ChameleonResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's url/params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(endpoint: str, manager: mock.MagicMock) -> list[dict[str, Any]]:
    source_response = chameleon_source(
        account_secret="secret",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )
    return [row for page in source_response.items() for row in page]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Chameleon account secret"),
            ("forbidden", 403, False, "Invalid Chameleon account secret"),
            ("rate_limited", 429, False, "status 429"),
            ("server_error", 500, False, "status 500"),
        ]
    )
    def test_status_maps_to_result(
        self, _name: str, status_code: int, expected_ok: bool, expected_fragment: str | None
    ) -> None:
        with mock.patch(CHAMELEON_SESSION_PATCH) as make_session:
            session = mock.MagicMock()
            session.get.return_value = mock.MagicMock(status_code=status_code)
            make_session.return_value = session
            ok, error = validate_credentials("secret")
            assert ok is expected_ok
            if expected_fragment is None:
                assert error is None
            else:
                assert error is not None and expected_fragment in error

    def test_network_error_is_inconclusive(self) -> None:
        with mock.patch(CHAMELEON_SESSION_PATCH) as make_session:
            session = mock.MagicMock()
            session.get.side_effect = requests.ConnectionError("boom")
            make_session.return_value = session
            ok, error = validate_credentials("secret")
            assert ok is False
            assert error is not None and "Could not reach Chameleon" in error

    def test_probe_sends_the_account_secret_header(self) -> None:
        with mock.patch(CHAMELEON_SESSION_PATCH) as make_session:
            session = mock.MagicMock()
            session.get.return_value = mock.MagicMock(status_code=200)
            make_session.return_value = session
            validate_credentials("secret")
            headers = session.get.call_args.kwargs["headers"]
            assert headers["X-Account-Secret"] == "secret"


class TestStandardEndpointPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_before_cursor_until_exhausted(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"segments": [{"id": "S1"}, {"id": "S2"}], "cursor": {"limit": 500, "before": "S2"}}),
                _response({"segments": [{"id": "S3"}], "cursor": {"limit": 500, "before": "S3"}}),
                _response({"segments": [], "cursor": {}}),
            ],
        )

        rows = _rows("segments", _make_manager())

        assert [r["id"] for r in rows] == ["S1", "S2", "S3"]
        assert [s["url"] for s in snapshots] == ["https://api.chameleon.io/v3/edit/segments"] * 3
        assert "before" not in snapshots[0]["params"]
        assert snapshots[0]["params"]["limit"] == 500
        assert snapshots[1]["params"]["before"] == "S2"
        assert snapshots[2]["params"]["before"] == "S3"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_cursor_missing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"tours": [{"id": "T1"}], "cursor": {}})])

        rows = _rows("tours", _make_manager())

        assert [r["id"] for r in rows] == ["T1"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_cursor_fails_to_advance(self, MockSession: mock.MagicMock) -> None:
        # A repeated cursor must terminate the sync instead of wedging it in an infinite loop.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"tours": [{"id": "T1"}], "cursor": {"before": "T1"}}),
                _response({"tours": [{"id": "T1"}], "cursor": {"before": "T1"}}),
            ],
        )

        rows = _rows("tours", _make_manager())

        assert [r["id"] for r in rows] == ["T1", "T1"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_is_an_empty_page(self, MockSession: mock.MagicMock) -> None:
        # Chameleon envelopes are tolerated when the data key is absent — zero rows, no crash.
        session = MockSession.return_value
        _wire(session, [_response({"cursor": {}})])

        assert _rows("tours", _make_manager()) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_after_each_page_with_more_to_come(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"segments": [{"id": "S1"}, {"id": "S2"}], "cursor": {"before": "S2"}}),
                _response({"segments": [{"id": "S3"}], "cursor": {}}),
            ],
        )

        manager = _make_manager()
        _rows("segments", manager)

        # Only the first page has a next cursor, so exactly one checkpoint is saved, pointing at it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ChameleonResumeConfig(before="S2")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_before(self, MockSession: mock.MagicMock) -> None:
        # When state exists, the first request must start from the saved cursor, not page one.
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"segments": [{"id": "S3"}], "cursor": {}})])

        rows = _rows("segments", _make_manager(ChameleonResumeConfig(before="S2")))

        assert [r["id"] for r in rows] == ["S3"]
        assert snapshots[0]["params"]["before"] == "S2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_secret_travels_via_framework_auth(self, MockSession: mock.MagicMock) -> None:
        # Framework api_key auth (not a hand-built header) so the secret is value-redacted from logs.
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"tours": [{"id": "T1"}], "cursor": {}})])

        _rows("tours", _make_manager())

        auth = snapshots[0]["auth"]
        assert auth.api_key == "secret"
        assert auth.name == "X-Account-Secret"
        assert auth.location == "header"
        assert session.headers.get("Accept") == "application/json"


class TestResponsesFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_surveys_and_stamps_survey_id(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"surveys": [{"id": "SV1"}, {"id": "SV2"}], "cursor": {}}),
                _response({"responses": [{"id": "R1"}, {"id": "R2"}], "cursor": {}}),
                _response({"responses": [{"id": "R3"}], "cursor": {}}),
            ],
        )

        rows = _rows("responses", _make_manager())

        assert rows == [
            {"id": "R1", "survey_id": "SV1"},
            {"id": "R2", "survey_id": "SV1"},
            {"id": "R3", "survey_id": "SV2"},
        ]
        assert [s["url"] for s in snapshots] == [
            "https://api.chameleon.io/v3/edit/surveys",
            "https://api.chameleon.io/v3/analyze/responses?id=SV1",
            "https://api.chameleon.io/v3/analyze/responses?id=SV2",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_within_a_survey(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"surveys": [{"id": "SV1"}], "cursor": {}}),
                _response({"responses": [{"id": "R1"}], "cursor": {"before": "R1"}}),
                _response({"responses": [{"id": "R2"}], "cursor": {}}),
            ],
        )

        rows = _rows("responses", _make_manager())

        assert [r["id"] for r in rows] == ["R1", "R2"]
        assert "before" not in snapshots[1]["params"]
        assert snapshots[2]["params"]["before"] == "R1"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_survey_deleted_mid_fan_out_is_skipped(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"surveys": [{"id": "SV1"}, {"id": "GONE"}, {"id": "SV2"}], "cursor": {}}),
                _response({"responses": [{"id": "R1"}], "cursor": {}}),
                _response({"error": "not found"}, status=404),
                _response({"responses": [{"id": "R2"}], "cursor": {}}),
            ],
        )

        rows = _rows("responses", _make_manager())

        assert [r["id"] for r in rows] == ["R1", "R2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_404_http_error_propagates(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"surveys": [{"id": "SV1"}], "cursor": {}}),
                _response({"error": "forbidden"}, status=403),
            ],
        )

        with pytest.raises(requests.HTTPError):
            _rows("responses", _make_manager())

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_fan_out_progress(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"surveys": [{"id": "SV1"}], "cursor": {}}),
                _response({"responses": [{"id": "R1"}], "cursor": {"before": "R1"}}),
                _response({"responses": [{"id": "R2"}], "cursor": {}}),
            ],
        )

        manager = _make_manager()
        _rows("responses", manager)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        # Mid-survey: the in-progress survey path and its cursor are checkpointed so a crash
        # resumes into the same survey at the saved page.
        assert saved[0] == ChameleonResumeConfig(
            fanout_state={"completed": [], "current": "/analyze/responses?id=SV1", "child_state": {"cursor": "R1"}}
        )
        # Survey finished: it lands in `completed` so a restart skips it.
        assert saved[-1] == ChameleonResumeConfig(
            fanout_state={"completed": ["/analyze/responses?id=SV1"], "current": None, "child_state": None}
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_by_skipping_completed_surveys(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"surveys": [{"id": "SV1"}, {"id": "SV2"}], "cursor": {}}),
                _response({"responses": [{"id": "R2"}], "cursor": {}}),
            ],
        )

        manager = _make_manager(
            ChameleonResumeConfig(
                fanout_state={"completed": ["/analyze/responses?id=SV1"], "current": None, "child_state": None}
            )
        )
        rows = _rows("responses", manager)

        assert rows == [{"id": "R2", "survey_id": "SV2"}]
        assert snapshots[1]["url"] == "https://api.chameleon.io/v3/analyze/responses?id=SV2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pre_migration_bookmark_restarts_fan_out_fresh(self, MockSession: mock.MagicMock) -> None:
        # An old-shape bookmark (survey_id + before) can't seed the framework fan-out state — the
        # sync restarts from the first survey and the merge dedupes re-pulled rows.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"surveys": [{"id": "SV1"}], "cursor": {}}),
                _response({"responses": [{"id": "R1"}], "cursor": {}}),
            ],
        )

        manager = _make_manager(ChameleonResumeConfig(before="R9", survey_id="DELETED"))
        rows = _rows("responses", manager)

        assert [r["id"] for r in rows] == ["R1"]


class TestResumeStateCompatibility:
    def test_pre_migration_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does `dataclass(**saved)` — state saved before the
        # framework migration must still construct.
        assert ChameleonResumeConfig(**{"before": "S2", "survey_id": "SV1"}) == ChameleonResumeConfig(
            before="S2", survey_id="SV1"
        )


class TestChameleonSourceResponse:
    @parameterized.expand(list(CHAMELEON_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        response = chameleon_source(
            account_secret="secret",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Chameleon returns newest-first; the watermark/ordering contract must reflect that.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
