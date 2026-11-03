from collections.abc import Iterator
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.models.scoping import team_scope

from products.stamphog.backend.facade.enums import ReviewMode, ReviewRunStatus, ReviewVerdict
from products.stamphog.backend.facade.tasks import route_pull_request_reviewers
from products.stamphog.backend.logic.routing.comment import ROUTING_COMMENT_MARKER
from products.stamphog.backend.logic.routing.cut import CUT_MODEL
from products.stamphog.backend.models import PullRequest, StamphogRepoConfig
from products.stamphog.backend.tasks.tasks import (
    ROUTING_SAFETY_NET_SECONDS,
    queue_routing_after_verdict,
    route_reviewers_safety_net,
)
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES, ROUTING_APP_SLUG, RoutingChain

REPO = "acme/widgets"
INSTALLATION_ID = "2002"
PR_NUMBER = 7
HEAD_SHA = "head-sha-1"

_OWNERS_FILES = {
    "owners.yaml": "version: 1\n",
    "products/alpha/owners.yaml": "version: 1\nowners: [team-alpha]\nadditions: [team-alpha]\n",
    "products/beta/owners.yaml": "version: 1\nowners: [team-beta]\n",
    "products/gamma/owners.yaml": "version: 1\nowners: ['@carol']\n",
    "products/alpha/a.py": "a = 1\n",
}
_CUT_BETA = {"cuts": [{"owner": "team-beta", "reason": "Only renames an import."}]}
SAFETY_NET_SCHEDULE = "products.stamphog.backend.tasks.tasks.route_reviewers_safety_net.apply_async"


def _file(path: str, status: str = "modified", lines: int = 10) -> dict[str, Any]:
    return {"filename": path, "status": status, "additions": lines, "deletions": 0, "patch": f"@@ -1 +1 @@\n+{path}"}


def _setup(
    chain: RoutingChain,
    team: Any,
    user: Any,
    *,
    routing_mode: str = "always",
    head_repo: str = REPO,
    draft: bool = False,
    state: str = "open",
    fork_labels: dict[str, str] | None = None,
    enabled: bool = True,
    review_mode: str = ReviewMode.ALL,
    author_type: str = "User",
    with_addition: bool = True,
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
            "user": {"login": "dana", "type": author_type},
            "author_association": "MEMBER",
            "labels": [],
            "head": {"sha": HEAD_SHA, "ref": "move-loader", "repo": {"full_name": head_repo}},
            "base": {"sha": "base-sha", "ref": "master", "repo": {"full_name": REPO}},
        },
        files=[
            _file("products/alpha/a.py", lines=40),
            # A file in a new directory exercises the owners-of-additions lookup and pins team-alpha.
            *([_file("products/alpha/new/b.py", status="added", lines=20)] if with_addition else []),
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
            enabled=enabled,
            review_mode=review_mode,
            routing_mode=routing_mode,
            routing_fork_labels=fork_labels or {},
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


def _seed_routing_comment(chain: RoutingChain, repo_config: StamphogRepoConfig) -> None:
    chain.recorder.issue_comments[(REPO, PR_NUMBER)] = [
        {
            "id": 555,
            "body": f"{ROUTING_COMMENT_MARKER}\nan earlier routing",
            "user": {"login": f"{ROUTING_APP_SLUG}[bot]", "type": "Bot"},
        }
    ]
    # The earlier routing that posted the comment recorded it, which is what makes a later one delete it.
    team_id = repo_config.team_id
    with team_scope(team_id):
        pr_obj, _ = PullRequest.objects.for_team(team_id).get_or_create(
            repo_config=repo_config, pr_number=PR_NUMBER, defaults={"team_id": team_id}
        )
        pr_obj.routing = {**(pr_obj.routing or {}), "comment_posted": True}
        pr_obj.save(update_fields=["routing"])


@pytest.mark.parametrize(
    "name,setup_kwargs,action",
    [
        ("routing_off", {"routing_mode": "off"}, "opened"),
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
    repo_config = _setup(routing_chain, team, user)
    _seed_routing_comment(routing_chain, repo_config)
    routing_chain.cut_model.answer = answer
    routing_chain.cut_model.error = error

    _route()

    assert [call["model"] for call in routing_chain.cut_model.calls] == [CUT_MODEL]
    assert _requested(routing_chain) == (expected_users, expected_teams)
    record = _stored(team.id)
    assert [cut["owner"] for cut in record["cut"]] == expected_cut
    assert record["head_sha"] == HEAD_SHA
    assert record["status"] == "done"
    assert record["comment_posted"] is bool(expected_cut)
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
def test_a_fork_skips_the_model_and_labels_the_teams_with_a_fork_label(team, user, routing_chain) -> None:
    # The label name comes from the config as written, with no naming rule applied to the slug.
    _setup(routing_chain, team, user, head_repo="outsider/widgets", fork_labels={"team-alpha": "area: alpha"})
    routing_chain.cut_model.answer = _CUT_BETA

    _route()

    assert routing_chain.cut_model.calls == []
    assert _requested(routing_chain) == ({"carol"}, {"team-beta"})
    assert [write["body"] for write in _writes(routing_chain, "add_labels")] == [{"labels": ["area: alpha"]}]
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


def _finish_review(
    repo_config: StamphogRepoConfig, status: ReviewRunStatus, verdict: ReviewVerdict, head_sha: str = HEAD_SHA
) -> None:
    # The function post_verdict and mark_review_failed call. Celery runs eagerly in tests.
    queue_routing_after_verdict(repo_config, pr_number=PR_NUMBER, head_sha=head_sha, status=status, verdict=verdict)


@pytest.fixture
def safety_net() -> Iterator[MagicMock]:
    with patch(SAFETY_NET_SCHEDULE) as schedule:
        yield schedule


def _open_fallback(chain: RoutingChain, team: Any, user: Any, **setup_kwargs: Any) -> StamphogRepoConfig:
    repo_config = _setup(chain, team, user, routing_mode="fallback", **setup_kwargs)
    _route()
    return repo_config


def _fire_safety_net(schedule: MagicMock) -> None:
    route_reviewers_safety_net.apply(kwargs=schedule.call_args.kwargs["kwargs"], throw=True)


def _push(chain: RoutingChain, head_sha: str) -> None:
    chain.recorder.prs[(REPO, PR_NUMBER)]["head"]["sha"] = head_sha


@pytest.mark.parametrize(
    "name,setup_kwargs",
    [
        ("review_disabled", {"enabled": False}),
        ("bot_author", {"author_type": "Bot"}),
        ("label_mode_without_label", {"review_mode": ReviewMode.LABEL}),
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_fallback_routes_at_once_when_stamphog_will_not_review(
    name: str, setup_kwargs: dict[str, Any], team, user, routing_chain, safety_net
) -> None:
    _open_fallback(routing_chain, team, user, **setup_kwargs)

    safety_net.assert_not_called()
    assert [call["model"] for call in routing_chain.cut_model.calls] == [CUT_MODEL]
    assert _requested(routing_chain) == ({"carol"}, {"team-alpha", "team-beta"})
    record = _stored(team.id)
    assert (record["mode"], record["trigger"], record["status"]) == ("fallback", "opened", "done")


@pytest.mark.parametrize(
    "name,with_addition,expected_teams,expect_comment",
    [
        # The new directory pins team-alpha, so only it is requested and the comment says why.
        ("pinned_owner", True, {"team-alpha"}, True),
        # Nobody is pinned: nobody is requested and an earlier routing comment goes away.
        ("nothing_pinned", False, set(), False),
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_fallback_approval_requests_only_pinned_owners(
    name: str,
    with_addition: bool,
    expected_teams: set[str],
    expect_comment: bool,
    team,
    user,
    routing_chain,
    safety_net,
) -> None:
    repo_config = _open_fallback(routing_chain, team, user, with_addition=with_addition)
    _seed_routing_comment(routing_chain, repo_config)

    assert routing_chain.recorder.github_writes == []
    assert safety_net.call_args.kwargs["countdown"] == ROUTING_SAFETY_NET_SECONDS
    assert _stored(team.id)["status"] == "waiting"

    _finish_review(repo_config, ReviewRunStatus.COMPLETED, ReviewVerdict.APPROVED)

    assert routing_chain.cut_model.calls == []
    assert _requested(routing_chain) == (set(), expected_teams)
    record = _stored(team.id)
    assert (record["trigger"], record["status"]) == ("verdict:approved", "done")
    edits = _writes(routing_chain, "issue_comment_edit")
    deletes = _writes(routing_chain, "delete_comment")
    if expect_comment:
        assert len(edits) == 1 and deletes == []
        assert "Stamphog approved this pull request" in edits[0]["body"]["body"]
    else:
        assert edits == [] and [delete["id"] for delete in deletes] == [555]

    # The safety net finds the approved head handled and the same verdict again requests nobody twice.
    _fire_safety_net(safety_net)
    _finish_review(repo_config, ReviewRunStatus.COMPLETED, ReviewVerdict.APPROVED)
    assert len(_writes(routing_chain, "request_reviewers")) == (1 if expected_teams else 0)


_HEAD_2 = "head-sha-2"
_APPROVED = ("verdict", HEAD_SHA, ReviewRunStatus.COMPLETED, ReviewVerdict.APPROVED)
_REFUSED = ("verdict", HEAD_SHA, ReviewRunStatus.COMPLETED, ReviewVerdict.REFUSED)
_FAILED = ("verdict", HEAD_SHA, ReviewRunStatus.FAILED, ReviewVerdict.NONE)
_WAIT = ("verdict", HEAD_SHA, ReviewRunStatus.COMPLETED, ReviewVerdict.WAIT)
_PUSH = ("push", _HEAD_2)
_NET = ("net",)


def _on_head_2(step: tuple[Any, ...]) -> tuple[Any, ...]:
    return (step[0], _HEAD_2, *step[2:])


@pytest.mark.parametrize(
    "name,steps,expected_request_calls,expected_trigger,expected_head,expected_safety_nets",
    [
        ("refused_routes_in_full", [_REFUSED, _NET], 1, "verdict:refused", HEAD_SHA, 1),
        ("failed_routes_in_full", [_FAILED, _NET], 1, "verdict:failed", HEAD_SHA, 1),
        ("safety_net_routes_a_waiting_head_once", [_NET, _NET], 1, "safety_net", HEAD_SHA, 1),
        # A WAIT re-reviews later, so the head keeps waiting and only the safety net routes it.
        ("wait_keeps_waiting_for_the_safety_net", [_WAIT, _NET], 1, "safety_net", HEAD_SHA, 1),
        # A WAIT on a head that never waited starts waiting there, with its own safety net.
        ("wait_on_a_push_starts_waiting", [_APPROVED, _PUSH, _on_head_2(_WAIT)], 1, "verdict:wait", _HEAD_2, 2),
        # The pinned-only routing does not count as the full routing, which runs once on head 2.
        (
            "approved_then_refused_push_routes_in_full_once",
            [_APPROVED, _PUSH, _on_head_2(_REFUSED), _on_head_2(_REFUSED), _NET],
            2,
            "verdict:refused",
            _HEAD_2,
            1,
        ),
        # Full routing happens at most once per pull request.
        (
            "refused_push_after_full_routing",
            [_REFUSED, _PUSH, _on_head_2(_REFUSED), _NET],
            1,
            "verdict:refused",
            HEAD_SHA,
            1,
        ),
        ("approval_after_full_routing", [_REFUSED, _PUSH, _on_head_2(_APPROVED)], 1, "verdict:refused", HEAD_SHA, 1),
        # A verdict for a moved head does nothing, and the safety net routes the current head.
        ("safety_net_routes_the_current_head", [_PUSH, _REFUSED, _NET], 1, "safety_net", _HEAD_2, 1),
    ],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_fallback_routes_each_pull_request_once_in_full(
    name: str,
    steps: list[tuple[Any, ...]],
    expected_request_calls: int,
    expected_trigger: str,
    expected_head: str,
    expected_safety_nets: int,
    team,
    user,
    routing_chain,
    safety_net,
) -> None:
    repo_config = _open_fallback(routing_chain, team, user)

    for step in steps:
        if step[0] == "verdict":
            _finish_review(repo_config, step[2], step[3], head_sha=step[1])
        elif step[0] == "push":
            _push(routing_chain, step[1])
        else:
            _fire_safety_net(safety_net)

    assert len(_writes(routing_chain, "request_reviewers")) == expected_request_calls
    assert safety_net.call_count == expected_safety_nets
    record = _stored(team.id)
    assert (record["trigger"], record["head_sha"]) == (expected_trigger, expected_head)
