import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.terraform_cloud import (
    TerraformCloudResumeConfig,
    TerraformCloudRetryableError,
    _fetch_json,
    _flatten_item,
    get_rows,
    terraform_cloud_source,
    validate_credentials,
)

BASE = "https://app.terraform.io/api/v2"


def _response(body: Any, status: int = 200, url: str = f"{BASE}/organizations") -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = url
    resp.headers["Content-Type"] = "application/vnd.api+json"
    return resp


def _page(items: list[dict], next_url: str | None = None) -> dict:
    body: dict[str, Any] = {"data": items}
    if next_url:
        body["links"] = {"next": next_url}
    return body


def _workspace(workspace_id: str, name: str) -> dict:
    return {"id": workspace_id, "type": "workspaces", "attributes": {"name": name}}


def _run_item(run_id: str, created_at: str) -> dict:
    return {"id": run_id, "type": "runs", "attributes": {"created-at": created_at, "status": "applied"}}


def _manager(resume: TerraformCloudResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _run_endpoint(
    endpoint: str,
    responses: list[Response],
    manager: MagicMock | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> tuple[list[list[dict]], MagicMock, MagicMock]:
    session = MagicMock()
    session.get.side_effect = responses
    manager = manager if manager is not None else _manager()
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.terraform_cloud.make_tracked_session",
        return_value=session,
    ):
        batches = list(
            get_rows(
                api_token="t",
                organization="acme",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
        )
    return batches, session, manager


class TestFlattenItem:
    def test_normalizes_attributes_and_extracts_relationship_ids(self) -> None:
        # created-at must land as created_at, or the declared incremental/partition fields
        # never match any row column and incremental sync silently breaks.
        row = _flatten_item(
            {
                "id": "run-1",
                "type": "runs",
                "attributes": {"created-at": "2026-01-01T00:00:00Z", "status-timestamps": {"applied-at": "x"}},
                "relationships": {
                    "workspace": {"data": {"id": "ws-1", "type": "workspaces"}},
                    "plan": {"data": {"id": "plan-1", "type": "plans"}},
                    "comments": {"data": []},
                    "created-by": {"data": None},
                },
            }
        )
        assert row == {
            "id": "run-1",
            "type": "runs",
            "created_at": "2026-01-01T00:00:00Z",
            "status_timestamps": {"applied_at": "x"},
            "workspace_id": "ws-1",
            "plan_id": "plan-1",
        }


class TestTopLevelEndpoints:
    def test_paginates_via_links_next_and_resolves_relative_urls(self) -> None:
        # The API documents absolute next links, but JSON:API allows relative ones — both must
        # advance pagination, and a missing link must terminate it (not loop on page one).
        responses = [
            _response(
                _page(
                    [{"id": "team-a", "type": "teams", "attributes": {"name": "a"}}],
                    "/api/v2/organizations/acme/teams?page%5Bnumber%5D=2",
                )
            ),
            _response(_page([{"id": "team-b", "type": "teams", "attributes": {"name": "b"}}])),
        ]
        batches, session, _ = _run_endpoint("teams", responses)
        assert [row["id"] for batch in batches for row in batch] == ["team-a", "team-b"]
        assert session.get.call_count == 2
        assert (
            session.get.call_args_list[1].args[0]
            == "https://app.terraform.io/api/v2/organizations/acme/teams?page%5Bnumber%5D=2"
        )

    def test_organizations_scoped_to_configured_org(self) -> None:
        # `/organizations` (no id) would return every org the token can access, leaking other
        # orgs' names, admin emails, and plan/SSO metadata. The endpoint must target only the
        # configured org and normalize its single-resource response to one row.
        responses = [_response({"data": {"id": "acme", "type": "organizations", "attributes": {"name": "acme"}}})]
        batches, session, _ = _run_endpoint("organizations", responses)
        assert session.get.call_args_list[0].args[0] == f"{BASE}/organizations/acme?page%5Bsize%5D=100"
        assert [row["id"] for batch in batches for row in batch] == ["acme"]

    def test_saves_resume_state_only_while_pages_remain(self) -> None:
        next_url = f"{BASE}/organizations/acme/projects?page%5Bnumber%5D=2"
        responses = [
            _response(_page([{"id": "prj-1", "attributes": {}}], next_url)),
            _response(_page([{"id": "prj-2", "attributes": {}}])),
        ]
        _, _, manager = _run_endpoint("projects", responses)
        # The final page must not be checkpointed — a retry resuming past the end would sync nothing.
        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            TerraformCloudResumeConfig(next_url=next_url)
        ]

    def test_resumes_from_saved_url(self) -> None:
        resume_url = f"{BASE}/organizations/acme/projects?page%5Bnumber%5D=3"
        responses = [_response(_page([{"id": "prj-9", "attributes": {}}]))]
        batches, session, _ = _run_endpoint(
            "projects", responses, manager=_manager(TerraformCloudResumeConfig(next_url=resume_url))
        )
        assert session.get.call_args_list[0].args[0] == resume_url
        assert [row["id"] for batch in batches for row in batch] == ["prj-9"]


class TestFanOutEndpoints:
    def test_runs_fan_out_stamps_workspace_and_bookmarks_progress(self) -> None:
        responses = [
            _response(_page([_workspace("ws-1", "app"), _workspace("ws-2", "infra")])),
            _response(_page([_run_item("run-1", "2026-01-02T00:00:00Z")])),  # ws-1 runs
            _response(_page([_run_item("run-2", "2026-01-01T00:00:00Z")])),  # ws-2 runs
        ]
        batches, session, manager = _run_endpoint("runs", responses)

        rows = [row for batch in batches for row in batch]
        # Every child row carries its parent workspace so the table joins back without
        # unpacking JSON:API relationships.
        assert [(row["id"], row["workspace_id"], row["workspace_name"]) for row in rows] == [
            ("run-1", "ws-1", "app"),
            ("run-2", "ws-2", "infra"),
        ]
        assert session.get.call_args_list[1].args[0] == f"{BASE}/workspaces/ws-1/runs?page%5Bsize%5D=100"
        # Crash between workspaces must resume at ws-2, not restart the whole fan-out.
        assert TerraformCloudResumeConfig(next_url=None, workspace_id="ws-2") in [
            call.args[0] for call in manager.save_state.call_args_list
        ]

    def test_state_versions_filter_by_workspace_name_and_org(self) -> None:
        # State versions have no per-workspace path; dropping the name filters would sync the
        # same global list once per workspace.
        responses = [
            _response(_page([_workspace("ws-1", "app")])),
            _response(_page([{"id": "sv-1", "attributes": {"serial": 4, "created-at": "2026-01-01T00:00:00Z"}}])),
        ]
        batches, session, _ = _run_endpoint("state_versions", responses)
        child_url = session.get.call_args_list[1].args[0]
        assert child_url.startswith(f"{BASE}/state-versions?")
        assert "filter%5Borganization%5D%5Bname%5D=acme" in child_url
        assert "filter%5Bworkspace%5D%5Bname%5D=app" in child_url
        assert [row["id"] for batch in batches for row in batch] == ["sv-1"]

    def test_state_versions_strip_signed_capability_urls(self) -> None:
        # State-version payloads carry signed state-file download/upload URLs. Persisting them
        # would let anyone who can query the warehouse table read or write raw Terraform state
        # (including secrets) without any HCP Terraform authorization.
        responses = [
            _response(_page([_workspace("ws-1", "app")])),
            _response(
                _page(
                    [
                        {
                            "id": "sv-1",
                            "attributes": {
                                "serial": 4,
                                "created-at": "2026-01-01T00:00:00Z",
                                "hosted-state-download-url": "https://archivist.terraform.io/v1/object/signed",
                                "hosted-json-state-download-url": "https://archivist.terraform.io/v1/object/signed-json",
                                "sanitized-state-download-url": "https://archivist.terraform.io/v1/object/sanitized",
                                "hosted-state-upload-url": "https://archivist.terraform.io/v1/object/upload",
                                "hosted-json-state-upload-url": "https://archivist.terraform.io/v1/object/upload-json",
                            },
                        }
                    ]
                )
            ),
        ]
        batches, _, _ = _run_endpoint("state_versions", responses)
        (row,) = [row for batch in batches for row in batch]
        assert not any("download_url" in key or "upload_url" in key for key in row)
        # The non-capability metadata still lands.
        assert row["serial"] == 4
        assert row["created_at"] == "2026-01-01T00:00:00Z"
        assert row["workspace_id"] == "ws-1"

    def test_resumes_into_bookmarked_workspace(self) -> None:
        resume_url = f"{BASE}/workspaces/ws-2/runs?page%5Bnumber%5D=5"
        responses = [
            _response(_page([_workspace("ws-1", "app"), _workspace("ws-2", "infra")])),
            _response(_page([_run_item("run-9", "2026-01-01T00:00:00Z")])),
        ]
        batches, session, _ = _run_endpoint(
            "runs", responses, manager=_manager(TerraformCloudResumeConfig(next_url=resume_url, workspace_id="ws-2"))
        )
        # ws-1 is skipped entirely; the resumed workspace starts at its saved page URL.
        assert session.get.call_count == 2
        assert session.get.call_args_list[1].args[0] == resume_url
        assert [row["id"] for batch in batches for row in batch] == ["run-9"]

    def test_restarts_when_bookmarked_workspace_no_longer_exists(self) -> None:
        responses = [
            _response(_page([_workspace("ws-1", "app")])),
            _response(_page([_run_item("run-1", "2026-01-01T00:00:00Z")])),
        ]
        batches, _, _ = _run_endpoint(
            "runs", responses, manager=_manager(TerraformCloudResumeConfig(next_url="http://x", workspace_id="ws-gone"))
        )
        assert [row["id"] for batch in batches for row in batch] == ["run-1"]

    def test_skips_workspace_deleted_mid_sync(self) -> None:
        responses = [
            _response(_page([_workspace("ws-1", "app"), _workspace("ws-2", "infra")])),
            _response({"errors": [{"status": "404"}]}, status=404),
            _response(_page([_run_item("run-2", "2026-01-01T00:00:00Z")])),
        ]
        batches, _, _ = _run_endpoint("runs", responses)
        # A workspace deleted between enumeration and fetch must not fail the whole sync.
        assert [row["id"] for batch in batches for row in batch] == ["run-2"]


class TestIncrementalPaginationTermination:
    def test_stops_paging_once_page_predates_watermark(self) -> None:
        # The API has no server-side time filter: without the client-side stop every
        # incremental sync re-walks each workspace's whole run history.
        next_url = f"{BASE}/workspaces/ws-1/runs?page%5Bnumber%5D=2"
        responses = [
            _response(_page([_workspace("ws-1", "app")])),
            # Older than watermark minus the 24h lookback -> stop, page 2 never requested.
            _response(_page([_run_item("run-old", "2026-01-01T00:00:00Z")], next_url)),
        ]
        batches, session, _ = _run_endpoint(
            "runs",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 10, tzinfo=UTC),
        )
        assert session.get.call_count == 2
        # The boundary page is still yielded; merge dedupes it on the primary key.
        assert [row["id"] for batch in batches for row in batch] == ["run-old"]

    def test_lookback_keeps_paging_through_recent_rows(self) -> None:
        # Runs mutate until they reach a final status, so rows inside the 24h lookback window
        # must be re-pulled even though they predate the raw watermark.
        next_url = f"{BASE}/workspaces/ws-1/runs?page%5Bnumber%5D=2"
        responses = [
            _response(_page([_workspace("ws-1", "app")])),
            _response(_page([_run_item("run-recent", "2026-01-09T18:00:00Z")], next_url)),
            _response(_page([_run_item("run-old", "2026-01-01T00:00:00Z")])),
        ]
        batches, session, _ = _run_endpoint(
            "runs",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 10, tzinfo=UTC),
        )
        assert session.get.call_count == 3
        assert [row["id"] for batch in batches for row in batch] == ["run-recent", "run-old"]

    def test_first_sync_without_watermark_walks_all_pages(self) -> None:
        next_url = f"{BASE}/workspaces/ws-1/runs?page%5Bnumber%5D=2"
        responses = [
            _response(_page([_workspace("ws-1", "app")])),
            _response(_page([_run_item("run-1", "2026-01-02T00:00:00Z")], next_url)),
            _response(_page([_run_item("run-2", "2026-01-01T00:00:00Z")])),
        ]
        batches, session, _ = _run_endpoint("runs", responses, should_use_incremental_field=True)
        assert session.get.call_count == 3
        assert [row["id"] for batch in batches for row in batch] == ["run-1", "run-2"]


class TestGetRowsUnknownEndpoint:
    def test_raises_for_unknown_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Unknown HCP Terraform endpoint"):
            list(
                get_rows(
                    api_token="t",
                    organization="acme",
                    endpoint="nope",
                    logger=MagicMock(),
                    resumable_source_manager=_manager(),
                )
            )


class TestFetchJsonStatusHandling:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response({}, status=status)
        # Call the undecorated function so tenacity's backoff doesn't sleep in the test.
        with pytest.raises(TerraformCloudRetryableError):
            _fetch_json.__wrapped__(session, f"{BASE}/organizations", MagicMock())  # type: ignore[attr-defined]

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_client_errors_propagate_as_httperror(self, status: int) -> None:
        # 4xx must surface as HTTPError so get_non_retryable_errors can match and permanently
        # fail the sync instead of retrying a dead credential forever.
        session = MagicMock()
        session.get.return_value = _response({"errors": []}, status=status)
        with pytest.raises(requests.HTTPError):
            _fetch_json.__wrapped__(session, f"{BASE}/organizations", MagicMock())  # type: ignore[attr-defined]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "valid", "message_fragment"),
        [
            (200, True, None),
            (401, False, "Invalid HCP Terraform API token"),
            (404, False, "not found or your API token cannot access it"),
            (500, False, "unexpected status"),
        ],
    )
    def test_maps_status_to_result(self, status: int, valid: bool, message_fragment: str | None) -> None:
        session = MagicMock()
        session.get.return_value = _response({}, status=status)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.terraform_cloud.make_tracked_session",
            return_value=session,
        ):
            ok, message = validate_credentials("token", "acme")
        assert ok is valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message

    def test_network_failure_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.terraform_cloud.make_tracked_session",
            return_value=session,
        ):
            ok, message = validate_credentials("token", "acme")
        assert ok is False
        assert message is not None


class TestSourceResponseShape:
    @pytest.mark.parametrize(
        ("endpoint", "partition_key", "sort_mode"),
        [
            ("organizations", None, "asc"),
            ("projects", None, "asc"),
            ("teams", None, "asc"),
            ("workspaces", None, "asc"),
            ("runs", "created_at", "desc"),
            ("state_versions", "created_at", "desc"),
        ],
    )
    def test_partition_and_sort_config(self, endpoint: str, partition_key: str | None, sort_mode: str) -> None:
        # Newest-first endpoints must declare desc, or the pipeline checkpoints the watermark
        # to ≈now after the first batch and mid-sync shutdowns lose rows. Partitioning is on
        # the STABLE created_at, never a mutating field.
        response = terraform_cloud_source(
            api_token="t",
            organization="acme",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == sort_mode
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.partition_mode == ("datetime" if partition_key else None)
