from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pulumicloud import (
    PulumiCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud import pulumi_cloud
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.pulumi_cloud import (
    AUDIT_LOGS_LOOKBACK_SECONDS,
    PAGE_SIZE,
    STACK_UPDATES_LOOKBACK_SECONDS,
    PulumiCloudResumeConfig,
    _as_unix_seconds,
    _flatten_update,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.settings import (
    PULUMI_CLOUD_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.source import PulumiCloudSource

STACKS_PATH = "/api/user/stacks"


def _run_rows(
    endpoint: str,
    script: Any,
    resume_state: PulumiCloudResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    driver = SourceDriver(PulumiCloudSource(), PulumiCloudSourceConfig(access_token="pul-test", organization="my-org"))
    result = driver.run(endpoint, script, resume_state=resume_state, **inputs)
    assert result.raised is None
    return result


def _json(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


def _stack_summary(project: str, stack: str) -> dict[str, Any]:
    return {"id": f"my-org/{project}/{stack}", "orgName": "my-org", "projectName": project, "stackName": stack}


class TestAsUnixSeconds:
    @parameterized.expand(
        [
            ("int", 1750000000, 1750000000),
            ("float", 1750000000.7, 1750000000),
            ("numeric_string", "1750000000", 1750000000),
            ("datetime", datetime(2026, 6, 15, tzinfo=UTC), 1781481600),
            ("bool", True, None),
            ("garbage_string", "not-a-timestamp", None),
            ("none", None, None),
        ]
    )
    def test_coercion(self, _name: str, value: Any, expected: int | None) -> None:
        # A miscoerced watermark would either crash the sync or silently disable the incremental
        # bound and re-pull full history every run.
        assert _as_unix_seconds(value) == expected


class TestStacks:
    def test_pagination_follows_continuation_token_and_saves_state_after_yield(self) -> None:
        result = _run_rows(
            "stacks",
            [
                _json({"stacks": [_stack_summary("proj", "dev")], "continuationToken": "tok-2"}),
                _json({"stacks": [_stack_summary("proj", "prod")]}),
            ],
        )

        assert result.params("continuationToken") == [None, "tok-2"]
        assert [r["stackName"] for r in result.rows] == ["dev", "prod"]
        # State is saved after yielding a page, and only while more pages remain — so a crash
        # re-yields the last page (merge dedupes) instead of skipping it.
        assert [s.next_token for s in result.saved_states] == ["tok-2"]

    def test_resume_starts_from_the_saved_token(self) -> None:
        result = _run_rows(
            "stacks",
            [_json({"stacks": [_stack_summary("proj", "prod")]})],
            resume_state=PulumiCloudResumeConfig(next_token="tok-2"),
        )

        assert result.params("continuationToken") == ["tok-2"]


class TestFlattenUpdate:
    def test_flattens_info_injects_stack_coordinates_and_drops_deployment(self) -> None:
        # The nested `info` carries the analytics payload (kind/result/times); the raw deployment
        # state snapshot can be enormous and must not reach the warehouse row, and `environment` can
        # hold credentials so it must be dropped too. The injected stack coordinates are what make
        # the composite primary key unique table-wide.
        item = {
            "updateID": "u-1",
            "version": 3,
            "latestVersion": 5,
            "requestedBy": {"githubLogin": "alice"},
            # A live access token the API returns on the outer update object — must never persist.
            "requestedByToken": "pul-secret-token",
            "info": {
                "kind": "update",
                "startTime": 1750000000,
                "endTime": 1750000060,
                "result": "succeeded",
                "resourceChanges": {"create": 2},
                "deployment": {"huge": "snapshot"},
                # Env vars supplied to the update — can carry cloud creds / PULUMI_CONFIG_PASSPHRASE.
                "environment": {"AWS_SECRET_ACCESS_KEY": "shh", "PULUMI_CONFIG_PASSPHRASE": "shh"},
            },
        }
        row = _flatten_update(item, "my-org", "proj", "dev")
        assert row == {
            "updateID": "u-1",
            "version": 3,
            "latestVersion": 5,
            "requestedBy": {"githubLogin": "alice"},
            "kind": "update",
            "startTime": 1750000000,
            "endTime": 1750000060,
            "result": "succeeded",
            "resourceChanges": {"create": 2},
            "orgName": "my-org",
            "projectName": "proj",
            "stackName": "dev",
        }

    def test_secret_config_ciphertext_is_stripped_but_plaintext_kept(self) -> None:
        # Secret config entries carry an encrypted `string` that is recoverable offline; it must not
        # reach the warehouse row. Non-secret entries and the secret's metadata are preserved.
        item = {
            "version": 1,
            "info": {
                "config": {
                    "aws:region": {"string": "us-east-1"},
                    "app:dbPassword": {"secret": True, "string": "AAABBBencrypted"},
                }
            },
        }
        row = _flatten_update(item, "my-org", "proj", "dev")
        assert row["config"]["aws:region"] == {"string": "us-east-1"}
        assert row["config"]["app:dbPassword"] == {"secret": True}


class TestStackUpdates:
    def _make_pages(self, start_times_per_page: list[list[int]]) -> Callable[[RecordedRequest], ScriptedResponse]:
        stack_list = {"stacks": [_stack_summary("proj", "dev")]}

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == STACKS_PATH:
                return _json(stack_list)
            page = int(request.param("page") or 1)
            if page > len(start_times_per_page):
                return _json({"updates": []})
            return _json(
                {
                    "updates": [
                        {"updateID": f"u-{t}", "version": t, "info": {"startTime": t}}
                        for t in start_times_per_page[page - 1]
                    ]
                }
            )

        return respond

    @staticmethod
    def _update_pages(result: DriveResult) -> list[str | None]:
        return [request.param("page") for request in result.requests if request.path != STACKS_PATH]

    def test_full_refresh_walks_pages_until_short_page(self) -> None:
        pages = [list(range(2 * PAGE_SIZE, PAGE_SIZE, -1)), list(range(PAGE_SIZE, PAGE_SIZE - 30, -1))]
        result = _run_rows("stack_updates", self._make_pages(pages))
        assert len(result.rows) == PAGE_SIZE + 30
        assert result.rows[0]["orgName"] == "my-org"

    def test_incremental_stops_once_a_page_predates_the_watermark(self) -> None:
        # Updates arrive newest-first with no server-side time filter; without the client-side stop
        # every incremental sync would re-walk each stack's full history (API-cost bug and memory
        # amplifier). Rows below the effective watermark must also not be re-yielded.
        effective_watermark = 2000
        raw_watermark = effective_watermark + STACK_UPDATES_LOOKBACK_SECONDS
        first_page = list(range(2050, 2050 - PAGE_SIZE, -1))  # full page reaching below 2000
        second_page = list(range(1950, 1850, -1))  # must never be fetched

        result = _run_rows(
            "stack_updates",
            self._make_pages([first_page, second_page]),
            incremental_field="startTime",
            db_incremental_field_last_value=raw_watermark,
        )

        assert self._update_pages(result) == ["1"]
        assert [r["startTime"] for r in result.rows] == list(range(2050, effective_watermark - 1, -1))

    def test_incremental_stops_on_full_page_without_usable_start_times(self) -> None:
        # If the API ever returns a full page of updates with no usable startTime, the newest-first
        # stop signal is absent; pagination must bail instead of walking to the page cap. The rows on
        # that page are still yielded (kept) so an untimestamped update isn't silently dropped.
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == STACKS_PATH:
                return _json({"stacks": [_stack_summary("proj", "dev")]})
            page = int(request.param("page") or 1)
            # A full page (would otherwise trigger another fetch) with no startTime on any row.
            return _json(
                {"updates": [{"updateID": f"u-{page}-{i}", "version": i, "info": {}} for i in range(PAGE_SIZE)]}
            )

        result = _run_rows(
            "stack_updates",
            respond,
            incremental_field="startTime",
            db_incremental_field_last_value=5000,
        )

        assert self._update_pages(result) == ["1"]
        assert len(result.rows) == PAGE_SIZE

    def test_fan_out_marks_stacks_completed_and_resume_skips_them(self) -> None:
        stacks = [_stack_summary("proj", "dev"), _stack_summary("proj", "prod")]

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == STACKS_PATH:
                return _json({"stacks": stacks})
            stack = request.path.split("/updates")[0].rsplit("/", 1)[-1]
            return _json({"updates": [{"updateID": f"u-{stack}", "version": 1, "info": {"startTime": 1}}]})

        result = _run_rows("stack_updates", respond)
        # Completed keys accumulate AFTER each stack's rows are yielded, so a crash mid-stack
        # re-processes that stack (merge dedupes) rather than skipping it.
        assert [s.completed_stack_keys for s in result.saved_states] == [
            ["my-org/proj/dev"],
            ["my-org/proj/dev", "my-org/proj/prod"],
        ]

        resumed = _run_rows(
            "stack_updates", respond, resume_state=PulumiCloudResumeConfig(completed_stack_keys=["my-org/proj/dev"])
        )
        assert [r["stackName"] for r in resumed.rows] == ["prod"]


class TestDeployments:
    def test_paginates_until_short_page_and_saves_next_page_after_yield(self) -> None:
        result = _run_rows(
            "deployments",
            [
                _json({"deployments": [{"id": f"d{i}", "created": "2026-06-01T00:00:00Z"} for i in range(PAGE_SIZE)]}),
                _json({"deployments": [{"id": "last", "created": "2026-05-01T00:00:00Z"}]}),
            ],
        )

        assert result.params("page") == ["1", "2"]
        assert len(result.rows) == PAGE_SIZE + 1
        # Saved AFTER yielding page 1: a crash between yield and save re-fetches page 1 (merge
        # dedupes) instead of skipping it.
        assert [s.page for s in result.saved_states] == [2]

    def test_resume_starts_from_the_saved_page(self) -> None:
        result = _run_rows(
            "deployments",
            [_json({"deployments": [{"id": "last"}]})],
            resume_state=PulumiCloudResumeConfig(page=2),
        )

        assert result.params("page") == ["2"]

    def test_empty_first_page_yields_nothing(self) -> None:
        # Orgs without Pulumi Deployments get an empty listing, not an error.
        result = _run_rows("deployments", [_json({"deployments": []})])
        assert result.rows == []

    def test_drops_environment_secrets_from_embedded_updates(self) -> None:
        # A deployment embeds the updates it ran, and each update's `environment` can hold cloud
        # credentials or PULUMI_CONFIG_PASSPHRASE; these rows skip `_flatten_update`, so the yield
        # path must strip them before they reach a queryable warehouse row.
        page = {
            "deployments": [
                {
                    "id": "d1",
                    "updates": [
                        {"updateID": "u1", "environment": {"AWS_SECRET_ACCESS_KEY": "shh"}},
                        {"updateID": "u2"},
                    ],
                }
            ]
        }
        result = _run_rows("deployments", [_json(page)])
        assert len(result.rows) == 1
        updates = result.rows[0]["updates"]
        assert all("environment" not in update for update in updates)
        assert [u["updateID"] for u in updates] == ["u1", "u2"]


class TestAuditLogs:
    @staticmethod
    def _pages() -> list[ScriptedResponse]:
        return [
            _json({"auditLogEvents": [{"timestamp": 100, "event": "stack.update"}], "continuationToken": "c-2"}),
            _json({"auditLogEvents": [{"timestamp": 90, "event": "member.added"}]}),
        ]

    def test_incremental_passes_server_side_start_time_lower_bound(self) -> None:
        # The v2 endpoint's startTime is the genuine server-side filter this table's incremental
        # support is built on; dropping it would re-pull the org's entire audit history every run.
        result = _run_rows(
            "audit_logs",
            self._pages(),
            incremental_field="timestamp",
            db_incremental_field_last_value=1750000000,
        )

        expected_start = 1750000000 - AUDIT_LOGS_LOOKBACK_SECONDS
        assert result.params("startTime") == [str(expected_start)] * 2
        assert result.params("continuationToken")[1] == "c-2"
        assert [r["timestamp"] for r in result.rows] == [100, 90]
        assert [s.next_token for s in result.saved_states] == ["c-2"]

    def test_a_full_refresh_run_sends_no_start_time_even_with_a_stale_watermark(self) -> None:
        # Passing a stale watermark on a full-refresh run would wrongly narrow the audit-log window.
        result = _run_rows("audit_logs", self._pages(), db_incremental_field_last_value=1750000000)

        assert result.params("startTime") == [None, None]


class TestResources:
    def test_cursor_advances_only_while_next_link_present(self) -> None:
        # The final page can still echo a cursor back; only the `next` link signals another page.
        # Following the echoed cursor would loop on the last page forever.
        result = _run_rows(
            "resources",
            [
                _json(
                    {
                        "resources": [{"urn": "urn:1", "project": "p", "stack": "s"}],
                        "pagination": {"cursor": "cur-2", "next": "https://api.pulumi.com/next"},
                    }
                ),
                _json(
                    {
                        "resources": [{"urn": "urn:2", "project": "p", "stack": "s"}],
                        "pagination": {"cursor": "cur-2"},
                    }
                ),
            ],
        )

        assert result.params("cursor") == [None, "cur-2"]
        assert [r["urn"] for r in result.rows] == ["urn:1", "urn:2"]
        assert [s.next_token for s in result.saved_states] == ["cur-2"]

    def test_empty_page_terminates(self) -> None:
        result = _run_rows("resources", [_json({"resources": []})])
        assert result.rows == []


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            assert validate_credentials("pul-test") is expected

        request = network.requests_log[0]
        assert request.url == "https://api.pulumi.com/api/user"
        assert request.headers["authorization"] == "token pul-test"
        # Responses carry arbitrary infrastructure data, so sample capture is off and the token is redacted.
        assert network.session_options[0]["capture"] is False
        assert network.session_options[0]["redact_values"] == ("pul-test",)


class TestFetchRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_are_retried(self, _name: str, status: int) -> None:
        bad = MagicMock(status_code=status)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"ok": True}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(pulumi_cloud._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = pulumi_cloud._fetch(session, "https://api.pulumi.com/api/user", {}, MagicMock())

        assert result == {"ok": True}
        assert session.get.call_count == 2

    def test_client_error_raises_without_retry(self) -> None:
        import requests

        bad = requests.Response()
        bad.status_code = 401
        session = MagicMock()
        session.get.return_value = bad

        with pytest.raises(requests.HTTPError):
            pulumi_cloud._fetch(session, "https://api.pulumi.com/api/user", {}, MagicMock())
        assert session.get.call_count == 1


class TestSourceResponse:
    @parameterized.expand(
        [
            ("stacks", "asc", None),
            # Newest-first endpoints report "desc" so the incremental watermark persists only at
            # successful job end; "asc" per-batch persistence would checkpoint the watermark to
            # ≈now after the first (newest) batch and lose everything a crashed run still owed.
            ("stack_updates", "desc", None),
            ("deployments", "desc", "created"),
            ("audit_logs", "desc", None),
            ("resources", "asc", "created"),
        ]
    )
    def test_sort_mode_partition_and_primary_keys(
        self, endpoint: str, expected_sort: str, partition_key: str | None
    ) -> None:
        empty = _json({"stacks": [], "deployments": [], "auditLogEvents": [], "resources": []})

        response = _run_rows(endpoint, always(empty)).response

        assert response is not None
        assert response.sort_mode == expected_sort
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.primary_keys == PULUMI_CLOUD_ENDPOINTS[endpoint].primary_keys
