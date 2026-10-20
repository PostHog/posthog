from typing import Any

import pytest

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


class TestZoomSourceResponse:
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
