from typing import Any

import time_machine
from unittest.mock import MagicMock

from parameterized import parameterized
from requests import Request, RequestException

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trunkio import (
    TrunkIoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.source import TrunkIoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.trunk_io import (
    TrunkCursorPaginator,
    TrunkIoResumeConfig,
    TrunkRepo,
    validate_credentials,
)

REPO = TrunkRepo(host="github.com", owner="my-org", name="my-repo")


def _ok(body: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json=body)


def _run(endpoint: str, script: Script, resume_state: TrunkIoResumeConfig | None = None, **kwargs: Any) -> DriveResult:
    config = TrunkIoSourceConfig(
        api_token="token",
        org_url_slug="my-org",
        repo_host=REPO.host,
        repo_owner=REPO.owner,
        repo_name=REPO.name,
        merge_queue_target_branch="main",
    )
    return SourceDriver(TrunkIoSource(), config).run(endpoint, script, resume_state=resume_state, **kwargs)


class TestTrunkCursorPaginator:
    @parameterized.expand(
        [
            ("first_page_omits_cursor", "", False),
            ("resumed_page_sends_cursor", "cursor-1", True),
        ]
    )
    def test_cursor_only_sent_once_we_have_one(self, _label: str, cursor: str, expect_cursor: bool) -> None:
        # `cursor` is uuid-typed on Trunk's side, so an empty string is not a valid "first page" value.
        paginator = TrunkCursorPaginator(cursor=cursor)
        request = Request(method="POST", url="https://api.trunk.io/v1/listPullRequests")
        paginator.init_request(request)

        assert request.json["take"] == 100
        assert ("cursor" in request.json) is expect_cursor

    @parameterized.expand(
        [
            ("has_next", {"nextCursor": "cursor-2"}, True),
            ("empty_cursor", {"nextCursor": ""}, False),
            ("missing_cursor", {}, False),
        ]
    )
    def test_update_state(self, _label: str, body: dict[str, Any], expected_has_next: bool) -> None:
        paginator = TrunkCursorPaginator()
        response = MagicMock()
        response.json.return_value = body
        paginator.update_state(response)

        assert paginator.has_next_page is expected_has_next
        assert paginator.get_resume_state() == ({"cursor": "cursor-2"} if expected_has_next else None)


class TestMergeQueuePullRequests:
    @time_machine.travel("2024-06-15T00:00:00Z", tick=False)
    def test_fresh_run_paginates_and_stamps_one_synced_through(self) -> None:
        result = _run(
            "MergeQueuePullRequests",
            [
                _ok({"pullRequests": [{"id": "pr-1"}], "nextCursor": "cursor-1"}),
                _ok({"pullRequests": [{"id": "pr-2"}], "nextCursor": ""}),
            ],
        )

        assert [row["id"] for row in result.rows] == ["pr-1", "pr-2"]
        # One stamp for the whole run, taken at its start, because a per-page `now()` would push
        # the watermark past rows a later page had not been fetched for yet.
        assert {row["synced_through"] for row in result.rows} == {"2024-06-15T00:00:00Z"}
        first_body = result.requests[0].json()
        assert first_body["targetBranch"] == "main"
        assert "since" not in first_body
        assert result.requests[1].json()["cursor"] == "cursor-1"
        assert result.final_state is None

    def test_incremental_run_sends_since(self) -> None:
        result = _run(
            "MergeQueuePullRequests",
            [_ok({"pullRequests": [], "nextCursor": ""})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-06-01T00:00:00Z",
        )

        assert result.requests[0].json()["since"] == "2024-06-01T00:00:00Z"


class TestV2Lists:
    @parameterized.expand(
        [
            ("test_collections", "TestCollections", "/v2/test-collections", {}),
            ("tests", "Tests", "/v2/tests", {}),
            (
                "unhealthy_tests",
                "UnhealthyTests",
                "/v2/tests",
                {"status": ("flaky,broken",), "include": ("metrics",), "period": ("7d",)},
            ),
            (
                "quarantined_tests",
                "QuarantinedTests",
                "/v2/tests",
                {"quarantineState": ("quarantined",), "include": ("metrics",), "period": ("7d",)},
            ),
            (
                "failing_tests",
                "FailingTests",
                "/v2/tests",
                {"sort": ("lastFailureAt",), "include": ("metrics",), "period": ("7d",)},
            ),
        ]
    )
    def test_paginates_v2_cursor_with_bearer_auth(
        self, _label: str, schema_name: str, expected_path: str, expected_filters: dict[str, tuple[str, ...]]
    ) -> None:
        result = _run(
            schema_name,
            [
                _ok({"data": [{"id": "a"}], "nextCursor": "cursor-1", "hasMore": True}),
                _ok({"data": [{"id": "b"}], "nextCursor": None, "hasMore": False}),
            ],
        )

        assert [row["id"] for row in result.rows] == ["a", "b"]
        assert [(r.method.upper(), r.origin, r.path) for r in result.requests] == [
            ("GET", "https://api.trunk.io", expected_path)
        ] * 2
        assert dict(result.requests[0].query) == {"limit": ("100",), **expected_filters}
        assert dict(result.requests[1].query) == {"limit": ("100",), **expected_filters, "cursor": ("cursor-1",)}
        assert result.requests[0].headers["authorization"] == "Bearer token"
        assert all(request.read_timeout == 60.0 for request in result.requests)
        assert [state.cursor for state in result.saved_states] == ["cursor-1"]
        assert result.final_state is None

    @time_machine.travel("2024-06-15T00:00:00Z", tick=False)
    def test_failing_tests_stamp_one_synced_through_per_run(self) -> None:
        result = _run(
            "FailingTests",
            [
                _ok({"data": [{"id": "a"}], "nextCursor": "cursor-1", "hasMore": True}),
                _ok({"data": [{"id": "b"}], "nextCursor": None, "hasMore": False}),
            ],
        )

        assert {row["synced_through"] for row in result.rows} == {"2024-06-15T00:00:00Z"}
        assert result.saved_states == [TrunkIoResumeConfig(cursor="cursor-1", synced_through="2024-06-15T00:00:00Z")]

    def test_resume_seeds_saved_cursor(self) -> None:
        result = _run(
            "Tests",
            [_ok({"data": [], "nextCursor": None, "hasMore": False})],
            resume_state=TrunkIoResumeConfig(cursor="cursor-resumed"),
        )

        assert result.requests[0].param("cursor") == "cursor-resumed"


class TestClientRedirectHandling:
    def test_redirect_is_refused_without_replaying_token(self) -> None:
        # A 30x from the API host must not be followed — `x-api-token` is a nonstandard header
        # `requests` wouldn't strip off-origin, so following the redirect would replay the token.
        result = _run(
            "MergeQueuePullRequests",
            always(ScriptedResponse(status=302, headers={"Location": "https://evil.example.com/steal"})),
        )

        assert isinstance(result.raised, ValueError)
        assert "redirect" in str(result.raised).lower()
        # Exactly one request went out (to the API host); the redirect target was never called.
        assert len(result.requests) == 1
        assert result.requests[0].origin == "https://api.trunk.io"


class TestValidateCredentials:
    def test_credential_check_disables_redirects(self) -> None:
        # Redirects off keeps the token from leaking to a redirect target during validation.
        with scripted_network([_ok({})]) as network:
            validate_credentials("token")

        assert network.session_options
        assert all(options["allow_redirects"] is False for options in network.session_options)

    def test_network_error_is_reported(self) -> None:
        with scripted_network(always(RequestException("boom"))):
            ok, error = validate_credentials("token")

        assert ok is False
        assert error is not None and "boom" in error
