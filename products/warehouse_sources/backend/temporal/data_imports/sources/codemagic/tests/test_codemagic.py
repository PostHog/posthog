import pytest
from unittest.mock import MagicMock

from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.codemagic import (
    CodemagicBuildsPaginator,
    CodemagicResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.settings import (
    CODEMAGIC_V1,
    CODEMAGIC_V3,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.source import CodemagicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codemagic import (
    CodemagicSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(CodemagicSource(), CodemagicSourceConfig(api_token="test-token"))


class TestCodemagicBuildsPaginator:
    def test_init_request_injects_skip(self) -> None:
        paginator = CodemagicBuildsPaginator(skip=30)
        request = Request(method="GET", url="https://api.codemagic.io/builds")
        paginator.init_request(request)
        assert request.params["skip"] == 30

    def test_update_request_injects_current_skip(self) -> None:
        paginator = CodemagicBuildsPaginator()
        response = MagicMock()
        paginator.update_state(response, data=[{"_id": "b1"}])
        request = Request(method="GET", url="https://api.codemagic.io/builds")
        paginator.update_request(request)
        assert request.params["skip"] == 1


class TestCodemagicSourceResumeBehavior:
    """End-to-end resume behaviour of the v1 source."""

    def test_sync_client_does_not_follow_redirects(self) -> None:
        # The token rides in a custom header requests preserves across cross-origin redirects, so
        # the sync client must pin allow_redirects off.
        result = _driver().run(
            "Applications",
            [ScriptedResponse(status=302, headers={"Location": "https://example.com/redirect"})],
            api_version=CODEMAGIC_V1,
        )

        assert result.paths == ["/apps"]
        assert result.raised is not None

    def test_builds_fresh_run_saves_skip_after_each_non_terminal_page(self) -> None:
        result = _driver().run(
            "Builds",
            [
                ScriptedResponse(json={"builds": [{"_id": "b1"}, {"_id": "b2"}]}),
                ScriptedResponse(json={"builds": [{"_id": "b3"}]}),
                ScriptedResponse(json={"builds": []}),
            ],
            api_version=CODEMAGIC_V1,
        )

        assert result.params("skip") == ["0", "2", "3"]
        assert result.saved_states == [CodemagicResumeConfig(skip=2), CodemagicResumeConfig(skip=3)]
        assert [row["_id"] for row in result.rows] == ["b1", "b2", "b3"]
        assert result.raised is None

    def test_builds_resume_seeds_paginator_with_saved_skip(self) -> None:
        result = _driver().run(
            "Builds",
            [ScriptedResponse(json={"builds": []})],
            resume_state=CodemagicResumeConfig(skip=60),
            api_version=CODEMAGIC_V1,
        )

        assert result.params("skip") == ["60"]
        assert result.raised is None


class TestCodemagicV3Source:
    def test_applications_page_through_user_apps(self) -> None:
        result = _driver().run(
            "Applications",
            [
                ScriptedResponse(json={"data": [{"id": "a1"}], "page_size": 100, "current_page": 1, "total_pages": 2}),
                ScriptedResponse(json={"data": [{"id": "a2"}], "page_size": 100, "current_page": 2, "total_pages": 2}),
            ],
            api_version=CODEMAGIC_V3,
        )

        assert [row["id"] for row in result.rows] == ["a1", "a2"]
        assert result.paths == ["/api/v3/user/apps", "/api/v3/user/apps"]
        assert result.params("page_size") == ["100", "100"]
        assert result.params("page") == ["1", "2"]
        assert result.response is not None
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_keys is None
        assert result.raised is None

    def test_builds_fan_out_over_teams_and_follow_cursor(self) -> None:
        result = _driver().run(
            "Builds",
            route(
                {
                    "/api/v3/user/teams": [
                        ScriptedResponse(
                            json={
                                "data": [{"id": "t1"}, {"id": "t2"}],
                                "page_size": 100,
                                "current_page": 1,
                                "total_pages": 1,
                            }
                        )
                    ],
                    "/api/v3/teams/t1/builds": [
                        ScriptedResponse(json={"data": [{"id": "b1"}], "page_size": 100, "cursor": "b1"}),
                        ScriptedResponse(json={"data": [{"id": "b2"}], "page_size": 100, "cursor": None}),
                    ],
                    "/api/v3/teams/t2/builds": [
                        ScriptedResponse(json={"data": [{"id": "b3"}], "page_size": 100, "cursor": None})
                    ],
                }
            ),
            api_version=CODEMAGIC_V3,
        )

        assert [row["id"] for row in result.rows] == ["b1", "b2", "b3"]
        assert result.paths == [
            "/api/v3/user/teams",
            "/api/v3/teams/t1/builds",
            "/api/v3/teams/t1/builds",
            "/api/v3/teams/t2/builds",
        ]
        assert result.params("page_size") == ["100", "100", "100", "100"]
        assert result.params("page") == ["1", None, None, None]
        assert result.params("cursor") == [None, None, "b1", None]
        assert result.saved_states[0] == CodemagicResumeConfig(
            completed=[], current="/api/v3/teams/t1/builds", child_state={"cursor": "b1"}
        )
        assert result.response is not None
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_keys == ["created_at"]
        assert result.raised is None

    def test_builds_resume_skips_completed_teams_and_seeds_cursor(self) -> None:
        result = _driver().run(
            "Builds",
            route(
                {
                    "/api/v3/user/teams": [
                        ScriptedResponse(
                            json={
                                "data": [{"id": "t1"}, {"id": "t2"}],
                                "page_size": 100,
                                "current_page": 1,
                                "total_pages": 1,
                            }
                        )
                    ],
                    "/api/v3/teams/t2/builds": [
                        ScriptedResponse(json={"data": [{"id": "b10"}], "page_size": 100, "cursor": None})
                    ],
                }
            ),
            resume_state=CodemagicResumeConfig(
                completed=["/api/v3/teams/t1/builds"],
                current="/api/v3/teams/t2/builds",
                child_state={"cursor": "b9"},
            ),
            api_version=CODEMAGIC_V3,
        )

        assert [row["id"] for row in result.rows] == ["b10"]
        assert result.paths == ["/api/v3/user/teams", "/api/v3/teams/t2/builds"]
        assert result.requests[1].param("page_size") == "100"
        assert result.requests[1].param("cursor") == "b9"
        assert result.raised is None

    def test_unknown_version_is_rejected(self) -> None:
        result = _driver().run("Builds", [], api_version="v2")

        assert isinstance(result.raised, ValueError)
        assert "Unsupported Codemagic API version" in str(result.raised)
        assert result.requests == []


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
        ],
    )
    def test_validate_credentials_maps_status_code(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            is_valid, error = validate_credentials("test-token", CODEMAGIC_V3)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error == "Invalid Codemagic API token"
        assert network.requests_log[0].path == "/api/v3/user/apps"

    @pytest.mark.parametrize(
        ("api_version", "expected_url"),
        [
            (CODEMAGIC_V1, "https://api.codemagic.io/apps"),
            (CODEMAGIC_V3, "https://codemagic.io/api/v3/user/apps"),
        ],
    )
    def test_validate_credentials_sends_auth_header_and_redacts_token(
        self, api_version: str, expected_url: str
    ) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("secret-token", api_version)

        # allow_redirects=False keeps the custom-header token from following a 3xx off-host.
        assert network.session_options == [{"redact_values": ("secret-token",), "allow_redirects": False}]
        assert len(network.requests_log) == 1
        assert network.requests_log[0].url == expected_url
        assert network.requests_log[0].headers["x-auth-token"] == "secret-token"
