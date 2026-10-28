from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.terraformcloud import (
    TerraformCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.source import TerraformCloudSource
from products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.terraform_cloud import (
    TerraformCloudResumeConfig,
    TerraformCloudRetryableError,
    _flatten_item,
    get_rows,
    validate_credentials,
)

BASE = "https://app.terraform.io/api/v2"


def _response(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body, headers={"Content-Type": "application/vnd.api+json"})


def _page(items: list[dict], next_url: str | None = None) -> dict:
    body: dict[str, Any] = {"data": items}
    if next_url:
        body["links"] = {"next": next_url}
    return body


def _workspace(workspace_id: str, name: str) -> dict:
    return {"id": workspace_id, "type": "workspaces", "attributes": {"name": name}}


def _run_item(run_id: str, created_at: str) -> dict:
    return {"id": run_id, "type": "runs", "attributes": {"created-at": created_at, "status": "applied"}}


def _run_endpoint(
    endpoint: str,
    script: Script,
    resume: TerraformCloudResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    driver = SourceDriver(TerraformCloudSource(), TerraformCloudSourceConfig(api_token="t", organization="acme"))
    return driver.run(endpoint, script, resume_state=resume, **inputs)


def _ids(result: DriveResult) -> list[str]:
    return [row["id"] for row in result.rows]


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
        result = _run_endpoint(
            "teams",
            [
                _response(
                    _page(
                        [{"id": "team-a", "type": "teams", "attributes": {"name": "a"}}],
                        "/api/v2/organizations/acme/teams?page%5Bnumber%5D=2",
                    )
                ),
                _response(_page([{"id": "team-b", "type": "teams", "attributes": {"name": "b"}}])),
            ],
        )
        assert _ids(result) == ["team-a", "team-b"]
        assert len(result.requests) == 2
        assert result.urls[1] == "https://app.terraform.io/api/v2/organizations/acme/teams?page%5Bnumber%5D=2"

    def test_organizations_scoped_to_configured_org(self) -> None:
        # `/organizations` (no id) would return every org the token can access, leaking other
        # orgs' names, admin emails, and plan/SSO metadata. The endpoint must target only the
        # configured org and normalize its single-resource response to one row.
        result = _run_endpoint(
            "organizations",
            [_response({"data": {"id": "acme", "type": "organizations", "attributes": {"name": "acme"}}})],
        )
        assert result.urls[0] == f"{BASE}/organizations/acme?page%5Bsize%5D=100"
        assert _ids(result) == ["acme"]

    def test_resumes_from_saved_url(self) -> None:
        resume_url = f"{BASE}/organizations/acme/projects?page%5Bnumber%5D=3"
        result = _run_endpoint(
            "projects",
            [_response(_page([{"id": "prj-9", "attributes": {}}]))],
            resume=TerraformCloudResumeConfig(next_url=resume_url),
        )
        assert result.urls[0] == resume_url
        assert _ids(result) == ["prj-9"]


class TestFanOutEndpoints:
    def test_state_versions_filter_by_workspace_name_and_org(self) -> None:
        # State versions have no per-workspace path; dropping the name filters would sync the
        # same global list once per workspace.
        result = _run_endpoint(
            "state_versions",
            [
                _response(_page([_workspace("ws-1", "app")])),
                _response(_page([{"id": "sv-1", "attributes": {"serial": 4, "created-at": "2026-01-01T00:00:00Z"}}])),
            ],
        )
        child_url = result.urls[1]
        assert child_url.startswith(f"{BASE}/state-versions?")
        assert "filter%5Borganization%5D%5Bname%5D=acme" in child_url
        assert "filter%5Bworkspace%5D%5Bname%5D=app" in child_url
        assert _ids(result) == ["sv-1"]

    def test_resumes_into_bookmarked_workspace(self) -> None:
        resume_url = f"{BASE}/workspaces/ws-2/runs?page%5Bnumber%5D=5"
        result = _run_endpoint(
            "runs",
            [
                _response(_page([_workspace("ws-1", "app"), _workspace("ws-2", "infra")])),
                _response(_page([_run_item("run-9", "2026-01-01T00:00:00Z")])),
            ],
            resume=TerraformCloudResumeConfig(next_url=resume_url, workspace_id="ws-2"),
        )
        # ws-1 is skipped entirely; the resumed workspace starts at its saved page URL.
        assert len(result.requests) == 2
        assert result.urls[1] == resume_url
        assert _ids(result) == ["run-9"]

    def test_skips_workspace_deleted_mid_sync(self) -> None:
        result = _run_endpoint(
            "runs",
            [
                _response(_page([_workspace("ws-1", "app"), _workspace("ws-2", "infra")])),
                _response({"errors": [{"status": "404"}]}, status=404),
                _response(_page([_run_item("run-2", "2026-01-01T00:00:00Z")])),
            ],
        )
        # A workspace deleted between enumeration and fetch must not fail the whole sync.
        assert result.raised is None
        assert _ids(result) == ["run-2"]


class TestIncrementalPaginationTermination:
    def test_lookback_keeps_paging_through_recent_rows(self) -> None:
        # Runs mutate until they reach a final status, so rows inside the 24h lookback window
        # must be re-pulled even though they predate the raw watermark.
        next_url = f"{BASE}/workspaces/ws-1/runs?page%5Bnumber%5D=2"
        result = _run_endpoint(
            "runs",
            [
                _response(_page([_workspace("ws-1", "app")])),
                _response(_page([_run_item("run-recent", "2026-01-09T18:00:00Z")], next_url)),
                _response(_page([_run_item("run-old", "2026-01-01T00:00:00Z")])),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 10, tzinfo=UTC),
        )
        assert len(result.requests) == 3
        assert _ids(result) == ["run-recent", "run-old"]

    def test_first_sync_without_watermark_walks_all_pages(self) -> None:
        next_url = f"{BASE}/workspaces/ws-1/runs?page%5Bnumber%5D=2"
        result = _run_endpoint(
            "runs",
            [
                _response(_page([_workspace("ws-1", "app")])),
                _response(_page([_run_item("run-1", "2026-01-02T00:00:00Z")], next_url)),
                _response(_page([_run_item("run-2", "2026-01-01T00:00:00Z")])),
            ],
            should_use_incremental_field=True,
        )
        assert len(result.requests) == 3
        assert _ids(result) == ["run-1", "run-2"]


class TestGetRowsUnknownEndpoint:
    def test_raises_for_unknown_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Unknown HCP Terraform endpoint"):
            list(
                get_rows(
                    api_token="t",
                    organization="acme",
                    endpoint="nope",
                    logger=MagicMock(),
                    resumable_source_manager=MagicMock(),
                )
            )


class TestFetchJsonStatusHandling:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        result = _run_endpoint("organizations", always(_response({}, status=status)))

        assert isinstance(result.raised, TerraformCloudRetryableError)

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_client_errors_propagate_as_httperror(self, status: int) -> None:
        # 4xx must surface as HTTPError so get_non_retryable_errors can match and permanently
        # fail the sync instead of retrying a dead credential forever.
        result = _run_endpoint("organizations", [_response({"errors": []}, status=status)])

        assert isinstance(result.raised, requests.HTTPError)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "valid", "message_fragment"),
        [
            (404, False, "not found or your API token cannot access it"),
        ],
    )
    def test_maps_status_to_result(self, status: int, valid: bool, message_fragment: str | None) -> None:
        with scripted_network(always(_response({}, status=status))):
            ok, message = validate_credentials("token", "acme")
        assert ok is valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message

    def test_network_failure_is_invalid(self) -> None:
        with scripted_network(always(ConnectionResetError("reset"))):
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
        result = _run_endpoint(endpoint, always(_response(_page([]))))

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == sort_mode
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.partition_mode == ("datetime" if partition_key else None)
