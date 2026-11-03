from typing import Any

import pytest

from posthog.models.scoping import team_scope

from products.stamphog.backend.facade.tasks import route_pull_request_reviewers
from products.stamphog.backend.logic.routing.comment import ROUTING_COMMENT_MARKER
from products.stamphog.backend.logic.routing.cut import CUT_MODEL
from products.stamphog.backend.models import PullRequest, StamphogRepoConfig
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES, ROUTING_APP_SLUG, RoutingChain

REPO = "acme/widgets"
INSTALLATION_ID = "2002"
PR_NUMBER = 7
HEAD_SHA = "head-sha-1"

_OWNERS_FILES = {
    "owners.yaml": "version: 1\n",
    "products/alpha/owners.yaml": "version: 1\nowners: [team-alpha]\n",
    "products/beta/owners.yaml": "version: 1\nowners: [team-beta]\n",
    "products/gamma/owners.yaml": "version: 1\nowners: ['@carol']\n",
    "products/alpha/a.py": "a = 1\n",
}
_CUT_BETA = {"cuts": [{"owner": "team-beta", "reason": "Only renames an import."}]}


def _file(path: str, status: str = "modified", lines: int = 10) -> dict[str, Any]:
    return {"filename": path, "status": status, "additions": lines, "deletions": 0, "patch": f"@@ -1 +1 @@\n+{path}"}


def _setup(
    chain: RoutingChain,
    team: Any,
    user: Any,
    *,
    routing_enabled: bool = True,
    head_repo: str = REPO,
    draft: bool = False,
    state: str = "open",
    label_only_teams: list[str] | None = None,
) -> StamphogRepoConfig:
    chain.recorder.policy_files.update(_OWNERS_FILES)
    chain.recorder.register_pr(
        REPO,
        PR_NUMBER,
        {
            "number": PR_NUMBER,
            "title": "Move the widget loader",
            "body": "Moves code around.",
            "state": state,
            "draft": draft,
            "updated_at": "2026-11-03T10:00:00Z",
            "user": {"login": "dana", "type": "User"},
            "head": {"sha": HEAD_SHA, "ref": "move-loader", "repo": {"full_name": head_repo}},
            "base": {"sha": "base-sha", "ref": "master", "repo": {"full_name": REPO}},
        },
        files=[
            _file("products/alpha/a.py", lines=40),
            # A file in a new directory exercises the owners-of-additions lookup.
            _file("products/alpha/new/b.py", status="added", lines=20),
            _file("products/beta/b.py", lines=2),
            _file("products/gamma/c.py", lines=5),
        ],
    )
    with team_scope(team.id):
        return StamphogRepoConfig.objects.create(
            team_id=team.id,
            repository=REPO,
            installation_id=INSTALLATION_ID,
            connected_by_user_id=user.id,
            routing_enabled=routing_enabled,
            routing_label_only_teams=label_only_teams or [],
        )


def _payload(action: str = "opened") -> dict[str, Any]:
    return {
        "action": action,
        "installation": {"id": INSTALLATION_ID},
        "repository": {"full_name": REPO},
        "pull_request": {"number": PR_NUMBER},
    }


def _route(action: str = "opened") -> None:
    route_pull_request_reviewers(payload=_payload(action), delivery_id="delivery-1")


def _writes(chain: RoutingChain, kind: str) -> list[dict[str, Any]]:
    return [write for write in chain.recorder.github_writes if write["kind"] == kind]


def _requested(chain: RoutingChain) -> tuple[set[str], set[str]]:
    users: set[str] = set()
    teams: set[str] = set()
    for write in _writes(chain, "request_reviewers"):
        users.update(write["body"].get("reviewers", []))
        teams.update(write["body"].get("team_reviewers", []))
    return users, teams


def _stored(team_id: int) -> dict[str, Any]:
    with team_scope(team_id):
        record = PullRequest.objects.for_team(team_id).get(pr_number=PR_NUMBER).routing
    assert isinstance(record, dict)
    return record


def _seed_routing_comment(chain: RoutingChain) -> None:
    chain.recorder.issue_comments[(REPO, PR_NUMBER)] = [
        {
            "id": 555,
            "body": f"{ROUTING_COMMENT_MARKER}\nan earlier routing",
            "user": {"login": f"{ROUTING_APP_SLUG}[bot]", "type": "Bot"},
        }
    ]


@pytest.mark.parametrize(
    "name,setup_kwargs,action",
    [
        ("routing_off", {"routing_enabled": False}, "opened"),
        ("draft", {"draft": True}, "opened"),
        ("closed", {"state": "closed"}, "ready_for_review"),
        ("other_action", {}, "synchronize"),
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_routing_skips_quietly(name: str, setup_kwargs: dict[str, Any], action: str, team, user, routing_chain) -> None:
    _setup(routing_chain, team, user, **setup_kwargs)

    _route(action)

    assert routing_chain.recorder.github_writes == []
    assert routing_chain.cut_model.calls == []
    with team_scope(team.id):
        assert not PullRequest.objects.for_team(team.id).filter(routing__isnull=False).exists()


@pytest.mark.parametrize(
    "name,answer,error,expected_users,expected_teams,expected_cut",
    [
        # The model cuts one owner: the other two are requested and the comment names the cut one.
        ("one_cut", _CUT_BETA, None, {"carol"}, {"team-alpha"}, ["team-beta"]),
        # Any model failure cuts nobody, and an earlier routing comment no longer holds.
        ("model_error", _CUT_BETA, RuntimeError("gateway down"), {"carol"}, {"team-alpha", "team-beta"}, []),
        ("unparseable_answer", "not json", None, {"carol"}, {"team-alpha", "team-beta"}, []),
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_routing_requests_the_owners_the_cut_step_keeps(
    name: str,
    answer: Any,
    error: Exception | None,
    expected_users: set[str],
    expected_teams: set[str],
    expected_cut: list[str],
    team,
    user,
    routing_chain,
) -> None:
    _setup(routing_chain, team, user)
    _seed_routing_comment(routing_chain)
    routing_chain.cut_model.answer = answer
    routing_chain.cut_model.error = error

    _route()

    assert [call["model"] for call in routing_chain.cut_model.calls] == [CUT_MODEL]
    assert _requested(routing_chain) == (expected_users, expected_teams)
    record = _stored(team.id)
    assert [cut["owner"] for cut in record["cut"]] == expected_cut
    assert record["head_sha"] == HEAD_SHA
    assert record["status"] == "done"
    assert record["additions_resolved"] is True
    assert {candidate["owner"] for candidate in record["candidates"]} == {"team-alpha", "team-beta", "@carol"}
    edits = _writes(routing_chain, "issue_comment_edit")
    deletes = _writes(routing_chain, "delete_comment")
    if expected_cut:
        assert len(edits) == 1 and deletes == []
        assert edits[0]["body"]["body"].startswith(ROUTING_COMMENT_MARKER)
        assert "team-beta" in edits[0]["body"]["body"]
    else:
        assert edits == [] and [delete["id"] for delete in deletes] == [555]
    event = routing_chain.captured.call_args.kwargs
    assert event["properties"]["stamphog_routing_cut"] == len(expected_cut)
    assert "Move the widget loader" not in str(event)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_fork_skips_the_model_and_labels_the_label_only_team(team, user, routing_chain) -> None:
    _setup(routing_chain, team, user, head_repo="outsider/widgets", label_only_teams=["team-alpha"])
    routing_chain.cut_model.answer = _CUT_BETA

    _route()

    assert routing_chain.cut_model.calls == []
    assert _requested(routing_chain) == ({"carol"}, {"team-beta"})
    assert [write["body"] for write in _writes(routing_chain, "add_labels")] == [{"labels": ["team/alpha"]}]
    assert _stored(team.id)["llm_skipped"] == "fork"


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_refused_bulk_request_falls_back_to_single_requests(team, user, routing_chain) -> None:
    _setup(routing_chain, team, user)
    # GitHub refuses the whole request when one reviewer cannot be requested, such as a stale login.
    routing_chain.recorder.unrequestable_reviewers = {"@carol"}

    _route()

    assert _requested(routing_chain) == (set(), {"team-alpha", "team-beta"})
    assert _stored(team.id)["refused"] == ["@carol"]


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_a_retry_for_the_same_head_requests_nobody_twice(team, user, routing_chain) -> None:
    _setup(routing_chain, team, user)
    routing_chain.cut_model.answer = _CUT_BETA

    _route()
    _route()

    assert len(_writes(routing_chain, "request_reviewers")) == 1
    assert len(routing_chain.cut_model.calls) == 1
