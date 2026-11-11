from collections.abc import Callable
from typing import Any

import pytest
from unittest import mock

import pyarrow as pa
import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.github import (
    GithubAuthMethodConfig,
    GithubSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.github import github
from products.warehouse_sources.backend.temporal.data_imports.sources.github.source import GithubSource


def _drive(endpoint: str, script: Script, **inputs: Any) -> DriveResult:
    config = GithubSourceConfig(
        auth_method=GithubAuthMethodConfig(github_integration_id=None, selection="pat", personal_access_token="tok"),
        repository="acme/widgets",
        repositories=None,
    )
    return SourceDriver(GithubSource(), config).run(endpoint, script, **inputs)


def _rows(result: DriveResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in result.items:
        assert isinstance(item, pa.Table)
        rows.extend(item.to_pylist())
    return rows


def _respond_by_path(responses: dict[str, ScriptedResponse]) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        for path in sorted(responses, key=len, reverse=True):
            if path in request.path:
                return responses[path]
        raise AssertionError(f"Unexpected URL requested: {request.url}")

    return respond


def _response(rows: list[dict[str, Any]]) -> mock.Mock:
    response = mock.Mock()
    response.json.return_value = rows
    response.headers = {}
    return response


def _fetch_page_by_url(responses_by_url: dict[str, mock.Mock]):
    def fetch_page(url: str, *_args: Any, **_kwargs: Any) -> mock.Mock:
        # Longest needle first, so "/orgs/acme/teams/core/members" never routes to "/orgs/acme/teams".
        for needle in sorted(responses_by_url, key=len, reverse=True):
            if needle in url:
                return responses_by_url[needle]
        raise AssertionError(f"Unexpected URL requested: {url}")

    return fetch_page


def _no_resume() -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = False
    return manager


@pytest.mark.parametrize(
    "endpoint,expect_raise",
    [
        # Org-scoped: a 404 on /orgs/{owner}/teams (user-owned repo, or no org access) must sync zero
        # rows, not fail the schema. teams walks it directly; team_members hits it via its fan-out parent.
        ("teams", False),
        ("team_members", False),
        # Repo-scoped: the repository probe 404s here too, so the repository really is gone and the
        # sync must stay fatal.
        ("issues", True),
    ],
)
def test_org_scoped_404_syncs_zero_rows_while_repo_scoped_404_stays_fatal(endpoint: str, expect_raise: bool) -> None:
    result = _drive(endpoint, always(ScriptedResponse(status=404, json={"message": "Not Found"})))
    if expect_raise:
        assert isinstance(result.raised, github.GithubRepositoryNotFoundError)
    else:
        assert result.raised is None
        assert _rows(result) == []


def test_team_members_child_404_stays_fatal_after_parent_listed() -> None:
    # The org-scoped skip covers only the parent teams walk (user-owned repo, no org). Once the org
    # resolves and a team is listed, a 404 on that team's members is unexpected and must surface, not
    # silently drop the team's members.
    result = _drive(
        "team_members",
        _respond_by_path(
            {
                "/orgs/acme/teams/core/members": ScriptedResponse(status=404, json={"message": "Not Found"}),
                "/orgs/acme/teams": ScriptedResponse(json=[{"id": 1, "slug": "core", "name": "Core"}]),
            }
        ),
    )
    assert result.paths == ["/orgs/acme/teams", "/orgs/acme/teams/core/members"]
    assert isinstance(result.raised, requests.exceptions.HTTPError)


def test_teams_derives_org_from_repository_and_yields_rows() -> None:
    # The org must come from the repo owner (acme/widgets -> acme). A regression in that derivation
    # would request /orgs/widgets/... or a repo-scoped path and sync nothing.
    result = _drive("teams", [ScriptedResponse(json=[{"id": 1, "slug": "core", "name": "Core"}])])

    assert result.raised is None
    assert result.paths == ["/orgs/acme/teams"]
    assert [row["id"] for row in _rows(result)] == [1]


def test_team_members_fan_out_injects_parent_fields_and_keeps_composite_rows() -> None:
    # The same user (id 7) belongs to two teams. Each membership must become its own row carrying
    # its team's id/slug/name, so ["team_id", "id"] stays unique table-wide. If parent injection or
    # the per-team fan-out regressed, the user would collapse to one row or lose team context.
    responses = {
        "/orgs/acme/teams/core/members": ScriptedResponse(json=[{"id": 7, "login": "ada"}]),
        "/orgs/acme/teams/growth/members": ScriptedResponse(json=[{"id": 7, "login": "ada"}]),
        "/orgs/acme/teams": ScriptedResponse(
            json=[
                {"id": 1, "slug": "core", "name": "Core"},
                {"id": 2, "slug": "growth", "name": "Growth"},
            ]
        ),
    }

    result = _drive("team_members", _respond_by_path(responses))
    assert result.raised is None
    rows = _rows(result)

    keyed = {(row["team_id"], row["id"]): row for row in rows}
    assert set(keyed) == {(1, 7), (2, 7)}
    assert keyed[(1, 7)]["team_slug"] == "core"
    assert keyed[(1, 7)]["team_name"] == "Core"
    assert keyed[(2, 7)]["team_slug"] == "growth"
    # The user's own fields pass through untouched.
    assert keyed[(1, 7)]["login"] == "ada"


def test_team_members_fan_out_respects_per_parent_page_cap() -> None:
    # A team whose member list paginates forever must be bounded by max_pages_per_parent, or a
    # broken Link header would loop the child walk indefinitely.
    child_page = ScriptedResponse(
        json=[{"id": 7, "login": "ada"}],
        headers={"Link": '<https://api.github.com/orgs/acme/teams/core/members?page=2>; rel="next"'},
    )

    script = _respond_by_path(
        {
            "/orgs/acme/teams/core/members": child_page,
            "/orgs/acme/teams": ScriptedResponse(json=[{"id": 1, "slug": "core", "name": "Core"}]),
        }
    )

    with mock.patch.object(github.GITHUB_ENDPOINTS["team_members"], "max_pages_per_parent", 3):
        result = _drive("team_members", script)

    assert result.raised is None
    assert result.paths.count("/orgs/acme/teams/core/members") == 3


@pytest.mark.parametrize("status_code", [401, 403, 404])
def test_org_permission_probe_reports_missing_grant(status_code: int) -> None:
    # A denial on the org teams probe must surface the friendly reason naming the grant, so the
    # schema picker can flag the org tables instead of the whole source failing. The probe must ride
    # the gated egress transport (github_request) like the data plane, not a raw session.
    response = mock.Mock(status_code=status_code, headers={}, text="Forbidden")
    with mock.patch.object(github, "github_request", return_value=response) as request:
        reason = github.check_org_endpoint_permission("tok", "acme/widgets")

    assert reason is not None
    assert "Members: Read" in reason
    assert "read:org" in reason
    assert "/orgs/acme/teams" in request.call_args.args[1]


@pytest.mark.parametrize(
    "api_version,expected_header",
    [
        # The pin resolved by the source class must reach the outgoing X-GitHub-Api-Version header for
        # each supported version; a broken thread-through would silently sync every source on one version.
        ("2022-11-28", "2022-11-28"),
        ("2026-03-10", "2026-03-10"),
        # Omitted (creation-time paths carry no pin) falls back to the legacy default.
        (None, "2022-11-28"),
    ],
)
def test_get_rows_sends_pinned_api_version_header(api_version: str | None, expected_header: str) -> None:
    extra: dict[str, Any] = {} if api_version is None else {"api_version": api_version}
    with mock.patch.object(
        github, "_fetch_page", side_effect=_fetch_page_by_url({"/repos/acme/widgets": _response([])})
    ) as fetch:
        list(
            github.get_rows(
                personal_access_token="tok",
                repository="acme/widgets",
                endpoint="issues",
                logger=mock.Mock(),
                resumable_source_manager=_no_resume(),
                **extra,
            )
        )

    assert fetch.call_args.args[1]["X-GitHub-Api-Version"] == expected_header


@pytest.mark.parametrize(
    "request_behavior",
    [
        pytest.param({"return_value": mock.Mock(status_code=200, headers={}, text="")}, id="ok"),
        pytest.param({"return_value": mock.Mock(status_code=500, headers={}, text="")}, id="server-error"),
        pytest.param({"return_value": mock.Mock(status_code=429, headers={}, text="")}, id="secondary-rate-limit"),
        pytest.param(
            {"return_value": mock.Mock(status_code=403, headers={"x-ratelimit-remaining": "0"}, text="")},
            id="primary-rate-limit-403",
        ),
        pytest.param({"side_effect": github.GitHubEgressBudgetExhausted("deferring")}, id="egress-budget-shed"),
        pytest.param({"side_effect": requests.exceptions.ConnectionError()}, id="network-error"),
    ],
)
def test_org_permission_probe_treats_non_denial_as_reachable(request_behavior: dict[str, Any]) -> None:
    # Only a real denial is a missing scope; a success, rate limit (even a 403-shaped one), 5xx,
    # egress-budget shed, or network error must not be mislabeled as a permission problem (which
    # would wrongly block the org tables).
    with mock.patch.object(github, "github_request", **request_behavior):
        assert github.check_org_endpoint_permission("tok", "acme/widgets") is None
