from typing import Any

import pytest
from unittest import mock

import pyarrow as pa
import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.github import github


def _response(rows: list[dict[str, Any]], next_url: str | None = None) -> mock.Mock:
    response = mock.Mock()
    response.json.return_value = rows
    response.headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return response


def _fetch_page_by_url(responses_by_url: dict[str, mock.Mock]):
    def fetch_page(url: str, *_args: Any, **_kwargs: Any) -> mock.Mock:
        for needle, response in responses_by_url.items():
            if needle in url:
                return response
        raise AssertionError(f"Unexpected URL requested: {url}")

    return fetch_page


def _no_resume() -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = False
    return manager


def _not_found_response() -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = 404
    response.ok = False
    response.headers = {}
    response.text = "Not Found"
    response.request = None
    response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "404 Client Error: Not Found for url", response=response
    )
    return response


@pytest.mark.parametrize(
    "endpoint,expect_raise",
    [
        # Org-scoped: a 404 on /orgs/{owner}/teams (user-owned repo, or no org access) must sync zero
        # rows, not fail the schema. teams walks it directly; team_members hits it via its fan-out parent.
        ("teams", False),
        ("team_members", False),
        # Repo-scoped: a 404 is a genuinely missing/inaccessible repo and must stay fatal.
        ("issues", True),
    ],
)
def test_org_scoped_404_syncs_zero_rows_while_repo_scoped_404_stays_fatal(endpoint: str, expect_raise: bool) -> None:
    session = mock.Mock()
    session.request.return_value = _not_found_response()

    with mock.patch.object(github, "make_tracked_session", return_value=session):
        rows = github.get_rows(
            personal_access_token="tok",
            repository="acme/widgets",
            endpoint=endpoint,
            logger=mock.Mock(),
            resumable_source_manager=_no_resume(),
        )
        if expect_raise:
            with pytest.raises(requests.exceptions.HTTPError):
                list(rows)
        else:
            assert list(rows) == []


def test_team_members_child_404_stays_fatal_after_parent_listed() -> None:
    # The org-scoped skip covers only the parent teams walk (user-owned repo, no org). Once the org
    # resolves and a team is listed, a 404 on that team's members is unexpected and must surface, not
    # silently drop the team's members.
    def fetch_page(url: str, *_args: Any, **kwargs: Any) -> mock.Mock:
        if "/orgs/acme/teams/core/members" in url:
            assert kwargs.get("skip_on_not_found") is False
            raise requests.exceptions.HTTPError("404 Client Error: Not Found for url", response=requests.Response())
        if "/orgs/acme/teams" in url:
            return _response([{"id": 1, "slug": "core", "name": "Core"}])
        raise AssertionError(f"Unexpected URL: {url}")

    with mock.patch.object(github, "_fetch_page", side_effect=fetch_page):
        with pytest.raises(requests.exceptions.HTTPError):
            list(
                github.get_rows(
                    personal_access_token="tok",
                    repository="acme/widgets",
                    endpoint="team_members",
                    logger=mock.Mock(),
                    resumable_source_manager=_no_resume(),
                )
            )


def _collect(endpoint: str, responses_by_url: dict[str, mock.Mock]) -> list[dict[str, Any]]:
    with mock.patch.object(github, "_fetch_page", side_effect=_fetch_page_by_url(responses_by_url)):
        tables = list(
            github.get_rows(
                personal_access_token="tok",
                repository="acme/widgets",
                endpoint=endpoint,
                logger=mock.Mock(),
                resumable_source_manager=_no_resume(),
            )
        )
    rows: list[dict[str, Any]] = []
    for table in tables:
        assert isinstance(table, pa.Table)
        rows.extend(table.to_pylist())
    return rows


def test_teams_derives_org_from_repository_and_yields_rows() -> None:
    # The org must come from the repo owner (acme/widgets -> acme). A regression in that derivation
    # would request /orgs/widgets/... or a repo-scoped path and sync nothing.
    responses = {"/orgs/acme/teams": _response([{"id": 1, "slug": "core", "name": "Core"}])}

    with mock.patch.object(github, "_fetch_page", side_effect=_fetch_page_by_url(responses)) as fetch:
        tables = list(
            github.get_rows(
                personal_access_token="tok",
                repository="acme/widgets",
                endpoint="teams",
                logger=mock.Mock(),
                resumable_source_manager=_no_resume(),
            )
        )

    assert any("/orgs/acme/teams" in call.args[0] for call in fetch.call_args_list)
    assert [row["id"] for table in tables for row in table.to_pylist()] == [1]


def test_team_members_fan_out_injects_parent_fields_and_keeps_composite_rows() -> None:
    # The same user (id 7) belongs to two teams. Each membership must become its own row carrying
    # its team's id/slug/name, so ["team_id", "id"] stays unique table-wide. If parent injection or
    # the per-team fan-out regressed, the user would collapse to one row or lose team context.
    # Member URLs first: substring matching would otherwise route them to the teams list, since
    # "/orgs/acme/teams" is a prefix of "/orgs/acme/teams/core/members".
    responses = {
        "/orgs/acme/teams/core/members": _response([{"id": 7, "login": "ada"}]),
        "/orgs/acme/teams/growth/members": _response([{"id": 7, "login": "ada"}]),
        "/orgs/acme/teams": _response(
            [
                {"id": 1, "slug": "core", "name": "Core"},
                {"id": 2, "slug": "growth", "name": "Growth"},
            ]
        ),
    }

    rows = _collect("team_members", responses)

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
    child_page = _response(
        [{"id": 7, "login": "ada"}], next_url="https://api.github.com/orgs/acme/teams/core/members?page=2"
    )

    def fetch_page(url: str, *_args: Any, **_kwargs: Any) -> mock.Mock:
        if "/orgs/acme/teams/core/members" in url:
            return child_page
        if "/orgs/acme/teams" in url:
            return _response([{"id": 1, "slug": "core", "name": "Core"}])
        raise AssertionError(f"Unexpected URL: {url}")

    with mock.patch.object(github.GITHUB_ENDPOINTS["team_members"], "max_pages_per_parent", 3):
        with mock.patch.object(github, "_fetch_page", side_effect=fetch_page) as fetch:
            list(
                github.get_rows(
                    personal_access_token="tok",
                    repository="acme/widgets",
                    endpoint="team_members",
                    logger=mock.Mock(),
                    resumable_source_manager=_no_resume(),
                )
            )

    child_calls = [c for c in fetch.call_args_list if "/orgs/acme/teams/core/members" in c.args[0]]
    assert len(child_calls) == 3


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
