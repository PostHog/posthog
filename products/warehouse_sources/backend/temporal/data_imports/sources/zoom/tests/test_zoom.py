from typing import Any

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import RESTClientRetryableError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zoom import ZoomSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zoom.source import ZoomSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zoom.zoom import (
    ZoomResumeConfig,
    validate_credentials,
)

_TOKEN = ScriptedResponse(json={"access_token": "tok", "expires_in": 3599})


def _driver() -> SourceDriver:
    return SourceDriver(ZoomSource(), ZoomSourceConfig(account_id="acc", client_id="cid", client_secret="secret"))


def _probe_script(token: ScriptedResponse, probe_status: int | None = None) -> Any:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/oauth/token":
            return token
        assert probe_status is not None, f"unexpected request {request.url}"
        return ScriptedResponse(status=probe_status, json={})

    return respond


class TestZoomResumeConfig:
    def test_defaults(self) -> None:
        assert ZoomResumeConfig() == ZoomResumeConfig(next_page_token="", user_index=0, fanout_state=None)

    def test_legacy_state_still_deserializes(self) -> None:
        # State saved by the previous implementation carried only next_page_token / user_index; the
        # added fanout_state field must default so ResumableSourceManager can still rebuild it.
        assert ZoomResumeConfig(next_page_token="tok", user_index=3) == ZoomResumeConfig(
            next_page_token="tok", user_index=3, fanout_state=None
        )


class TestTopLevelRows:
    def test_first_request_omits_token_then_carries_cursor(self) -> None:
        result = _driver().run(
            "users",
            route(
                {
                    "/oauth/token": [_TOKEN],
                    "/users": [
                        ScriptedResponse(json={"users": [{"id": "u1"}], "next_page_token": "t1"}),
                        ScriptedResponse(json={"users": [{"id": "u2"}], "next_page_token": ""}),
                    ],
                }
            ),
        )

        user_requests = [request for request in result.requests if request.path == "/v2/users"]
        assert user_requests[0].param("next_page_token") is None
        assert user_requests[0].param("page_size") == "300"
        assert user_requests[1].param("next_page_token") == "t1"

    def test_resume_seeds_first_request_with_saved_token(self) -> None:
        result = _driver().run(
            "users",
            route(
                {
                    "/oauth/token": [_TOKEN],
                    "/users": [ScriptedResponse(json={"users": [{"id": "u9"}], "next_page_token": ""})],
                }
            ),
            resume_state=ZoomResumeConfig(next_page_token="resumed"),
        )

        user_requests = [request for request in result.requests if request.path == "/v2/users"]
        assert user_requests[0].param("next_page_token") == "resumed"


class TestFanOutRows:
    def test_resume_skips_already_completed_user(self) -> None:
        result = _driver().run(
            "meetings",
            route(
                {
                    "/oauth/token": [_TOKEN],
                    "/users": [ScriptedResponse(json={"users": [{"id": "u1"}, {"id": "u2"}], "next_page_token": ""})],
                    "/users/u2/meetings": [ScriptedResponse(json={"meetings": [{"id": 2}], "next_page_token": ""})],
                }
            ),
            resume_state=ZoomResumeConfig(
                fanout_state={"completed": ["/users/u1/meetings"], "current": None, "child_state": None}
            ),
        )

        # u1 was already completed, so its meetings endpoint is never requested again.
        assert result.rows == [{"id": 2}]
        assert "/v2/users/u1/meetings" not in result.paths
        assert "/v2/users/u2/meetings" in result.paths

    @pytest.mark.parametrize(
        "endpoint,parent_key,parent_path,instances_path,participants_root,parent_column",
        [
            (
                "meeting_participants",
                "meetings",
                "/users/u1/meetings",
                "/past_meetings/{id}/instances",
                "/past_meetings",
                "meeting",
            ),
            (
                "webinar_participants",
                "webinars",
                "/users/u1/webinars",
                "/past_webinars/{id}/instances",
                "/past_webinars",
                "webinar",
            ),
        ],
    )
    @pytest.mark.parametrize(
        "uuid,encoded",
        [
            ("abcDEF12==", "abcDEF12%3D%3D"),
            ("ab/c+d==", "ab%2Fc%2Bd%3D%3D"),
            ("/abcd==", "%252Fabcd%253D%253D"),
            ("ab//cd==", "ab%252F%252Fcd%253D%253D"),
        ],
    )
    def test_participants_read_each_ended_instance_by_encoded_uuid(
        self,
        endpoint: str,
        parent_key: str,
        parent_path: str,
        instances_path: str,
        participants_root: str,
        parent_column: str,
        uuid: str,
        encoded: str,
    ) -> None:
        participant = {"id": "p1", "user_id": "16778240", "join_time": "2026-01-05T10:00:00Z"}
        responses = {
            "/oauth/token": _TOKEN,
            "/v2/users": ScriptedResponse(json={"users": [{"id": "u1"}], "next_page_token": ""}),
            f"/v2{parent_path}": ScriptedResponse(json={parent_key: [{"id": 111}, {"id": 222}], "next_page_token": ""}),
            # 222 never took place: Zoom answers 404 and that parent is skipped.
            "/v2" + instances_path.format(id=111): ScriptedResponse(
                json={parent_key: [{"uuid": uuid, "start_time": "2026-01-05T10:00:00Z"}]}
            ),
            "/v2" + instances_path.format(id=222): ScriptedResponse(status=404, json={"code": 3001}),
            f"/v2{participants_root}/{encoded}/participants": ScriptedResponse(
                json={"participants": [participant], "next_page_token": ""}
            ),
        }

        def respond(request: RecordedRequest) -> ScriptedResponse:
            assert request.path in responses, f"unexpected request {request.path}"
            return responses[request.path]

        result = _driver().run(endpoint, respond)

        assert result.rows == [{**participant, f"{parent_column}_id": 111, f"{parent_column}_uuid": uuid}]

    @pytest.mark.parametrize(
        "endpoint,parent_key,parent_path,registrants_root,parent_column",
        [
            ("meeting_registrants", "meetings", "/users/u1/meetings", "/meetings", "meeting_id"),
            ("webinar_registrants", "webinars", "/users/u1/webinars", "/webinars", "webinar_id"),
        ],
    )
    def test_registrants_carry_parent_id_and_skip_unreadable_parent(
        self, endpoint: str, parent_key: str, parent_path: str, registrants_root: str, parent_column: str
    ) -> None:
        result = _driver().run(
            endpoint,
            route(
                {
                    "/oauth/token": [_TOKEN],
                    "/v2/users": [ScriptedResponse(json={"users": [{"id": "u1"}], "next_page_token": ""})],
                    parent_path: [
                        ScriptedResponse(json={parent_key: [{"id": 111}, {"id": 222}], "next_page_token": ""})
                    ],
                    f"{registrants_root}/111/registrants": [
                        ScriptedResponse(status=400, json={"code": 200, "message": "No permission."})
                    ],
                    f"{registrants_root}/222/registrants": [
                        ScriptedResponse(json={"registrants": [{"id": "r1"}], "next_page_token": "t1"}),
                        ScriptedResponse(json={"registrants": [{"id": "r2"}], "next_page_token": ""}),
                    ],
                }
            ),
        )

        assert result.rows == [{"id": "r1", parent_column: 222}, {"id": "r2", parent_column: 222}]
        registrant_requests = [r for r in result.requests if r.path == f"/v2{registrants_root}/222/registrants"]
        assert [r.param("next_page_token") for r in registrant_requests] == [None, "t1"]

    def test_expired_page_token_fails_instead_of_truncating(self) -> None:
        responses = {
            "/oauth/token": _TOKEN,
            "/v2/users": ScriptedResponse(json={"users": [{"id": "u1"}], "next_page_token": ""}),
            "/v2/users/u1/meetings": ScriptedResponse(json={"meetings": [{"id": 111}], "next_page_token": ""}),
        }

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v2/meetings/111/registrants":
                if request.param("next_page_token") is None:
                    return ScriptedResponse(json={"registrants": [{"id": "r1"}], "next_page_token": "t1"})
                return ScriptedResponse(status=400, json={"code": 300, "message": "next_page_token expired"})
            return responses[request.path]

        with patch("time.sleep"):
            result = _driver().run("meeting_registrants", respond)

        assert isinstance(result.raised, RESTClientRetryableError)


class TestZoomSourceResponse:
    @pytest.mark.parametrize(
        "endpoint,resumable",
        [
            ("users", True),
            ("meetings", True),
            ("webinars", True),
            ("meeting_registrants", False),
            ("webinar_registrants", False),
            ("meeting_participants", False),
            ("webinar_participants", False),
        ],
    )
    def test_chained_tables_are_not_resumable(self, endpoint: str, resumable: bool) -> None:
        assert ZoomSource().resume_covers_run(incremental_or_append=False, schema_name=endpoint) is resumable

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return _TOKEN
            return ScriptedResponse(json={"users": [], "next_page_token": ""})

        result = _driver().run(endpoint, respond)

        assert result.response is not None
        assert result.response.supports_resume is resumable

    @pytest.mark.parametrize("endpoint", ["users", "meetings", "webinars"])
    def test_primary_keys_per_endpoint(self, endpoint: str) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/oauth/token":
                return _TOKEN
            return ScriptedResponse(json={"users": [], "meetings": [], "webinars": [], "next_page_token": ""})

        result = _driver().run(endpoint, respond)

        assert result.response is not None
        assert result.response.primary_keys == ["id"]


class TestValidateCredentials:
    def test_bad_credentials_return_false(self) -> None:
        with scripted_network(_probe_script(ScriptedResponse(status=400, json={"error": "invalid_client"}))):
            ok, error = validate_credentials("acc", "cid", "secret")
        assert ok is False
        assert error is not None

    def test_source_create_only_validates_token(self) -> None:
        with scripted_network(_probe_script(_TOKEN)) as network:
            ok, error = validate_credentials("acc", "cid", "secret", schema_name=None)
        assert ok is True
        assert error is None
        # No scoped endpoint probe at source-create.
        assert [request.path for request in network.requests_log] == ["/oauth/token"]

    def test_schema_probe_success(self) -> None:
        with scripted_network(_probe_script(_TOKEN, probe_status=200)):
            ok, error = validate_credentials("acc", "cid", "secret", schema_name="users")
        assert ok is True
        assert error is None

    def test_schema_probe_missing_scope_401(self) -> None:
        with scripted_network(_probe_script(_TOKEN, probe_status=401)):
            ok, error = validate_credentials("acc", "cid", "secret", schema_name="users")
        assert ok is False
        assert error is not None and "scope" in error

    def test_schema_probe_unexpected_status(self) -> None:
        with scripted_network(_probe_script(_TOKEN, probe_status=500)):
            ok, error = validate_credentials("acc", "cid", "secret", schema_name="users")
        assert ok is False
        assert error is not None and "500" in error
