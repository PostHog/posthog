import statistics
from types import SimpleNamespace
from typing import Any

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.errors import QueryError

from products.engineering_analytics.backend.facade.contracts import FrictionGroup
from products.engineering_analytics.backend.logic.friction import (
    MIN_PULL_REQUESTS,
    FrictionScorer,
    PullRequestFriction,
    build_author_friction,
    build_author_friction_detail,
    build_pull_request_friction,
)

# "Typical" differs in case from the author login, as the membership snapshot can.
_MEMBERS = {"pair": ["typical", "calm"], "everyone": ["blocked", "Typical", "calm", "newcomer"]}


def _pr(author: str, number: int, **friction: Any) -> PullRequestFriction:
    values: dict[str, Any] = {
        "push_count": 1,
        "flake_red_count": 0,
        "master_red_count": 0,
        "unknown_red_count": 0,
        "own_red_count": 0,
        "futile_rerun_count": 0,
        "ci_wait_seconds": (600.0,),
        "first_approval_wait_seconds": 3 * 3600.0,
        "pushes_after_approval": 0,
        "queue_seconds": 20 * 60.0,
        "kickout_count": 0,
        **friction,
    }
    return PullRequestFriction(
        number=number, repo_owner="PostHog", repo_name="posthog", author=author, author_avatar_url="", **values
    )


def _population() -> list[PullRequestFriction]:
    rows = []
    for i in range(6):
        rows.append(_pr("calm", 100 + i))
        rows.append(_pr("typical", 200 + i, own_red_count=1, push_count=2, first_approval_wait_seconds=8 * 3600.0))
        rows.append(
            _pr(
                "blocked",
                300 + i,
                master_red_count=2,
                futile_rerun_count=3,
                kickout_count=2,
                queue_seconds=3 * 3600.0,
            )
        )
    rows.extend(_pr("newcomer", 400 + i, master_red_count=5) for i in range(MIN_PULL_REQUESTS - 1))
    return rows


def _row(pr: PullRequestFriction) -> tuple:
    return (
        pr.number,
        pr.repo_owner,
        pr.repo_name,
        pr.author,
        pr.author_avatar_url,
        pr.push_count,
        pr.flake_red_count,
        pr.master_red_count,
        pr.unknown_red_count,
        pr.own_red_count,
        pr.futile_rerun_count,
        list(pr.ci_wait_seconds),
        pr.first_approval_wait_seconds,
        pr.pushes_after_approval,
        pr.queue_seconds,
        pr.kickout_count,
    )


class _Curated:
    """The slice of CuratedGitHubSource the friction read uses."""

    repository = "PostHog/posthog"
    source_id = "0192f000-0000-7000-8000-000000000001"

    def __init__(self, rows: list[tuple] | None, members: dict[str, list[str]] | None) -> None:
        self._rows = rows
        self._members = members
        self.friction_placeholders: dict[str, Any] = {}

    def members_source(self) -> str | None:
        return None if self._members is None else "(SELECT 1)"

    def pr_source(self) -> str:
        return "(SELECT 1)"

    def run_paged(self, sql: str, *, query_type: str, **kwargs: Any) -> list[tuple]:
        if query_type == "engineering_analytics.author_friction_memberships":
            return [(team, handle) for team, handles in (self._members or {}).items() for handle in handles]
        self.friction_placeholders = kwargs["placeholders"]
        if self._rows is None:
            raise QueryError("Unknown table `engineering_analytics_pr_friction`.")
        return self._rows

    def run(self, sql: str, *, placeholders: dict[str, Any], **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(results=[(number, f"PR {number}") for number in placeholders["numbers"].value])


class TestFrictionScore(SimpleTestCase):
    def test_scores_order_experiences_around_the_typical_author(self) -> None:
        items = FrictionScorer(_population()).score()

        assert [item.author for item in items] == ["blocked", "typical", "calm"]
        assert statistics.fmean(item.score for item in items) == pytest.approx(1.0)
        for item in items:
            assert sum(share.score for share in item.groups) == pytest.approx(item.score)
            assert item.rank_low <= item.rank <= item.rank_high

    def test_unqueued_pull_requests_count_as_no_queue_friction(self) -> None:
        rows = [_pr("always_queued", 500 + i, queue_seconds=2 * 3600.0) for i in range(4)]
        rows += [_pr("once_queued", 600, queue_seconds=2 * 3600.0)]
        rows += [_pr("once_queued", 601 + i, queue_seconds=None, kickout_count=None) for i in range(3)]

        queue = {
            item.author: next(share.score for share in item.groups if share.group == FrictionGroup.QUEUE)
            for item in FrictionScorer(rows).score()
        }

        assert queue["once_queued"] < queue["always_queued"]

    @parameterized.expand(
        [
            ("no_view_yet", None, None, False, [], []),
            (
                "whole_repository",
                _population(),
                None,
                True,
                [("blocked", 1), ("typical", 2), ("calm", 3)],
                ["everyone"],
            ),
            ("team_keeps_repository_ranks", _population(), "pair", True, [("typical", 2), ("calm", 3)], ["everyone"]),
        ]
    )
    def test_read(
        self,
        _name: str,
        prs: list[PullRequestFriction] | None,
        github_team: str | None,
        available: bool,
        expected: list[tuple[str, int]],
        expected_teams: list[str],
    ) -> None:
        curated = _Curated([_row(pr) for pr in prs] if prs is not None else None, _MEMBERS)

        friction = build_author_friction(curated=curated, github_team=github_team)  # type: ignore[arg-type]

        assert friction.available is available
        assert [(item.author, item.rank) for item in friction.items] == expected
        # The view unions every source of the team, so the read must keep to its own.
        assert curated.friction_placeholders["source_id"].value == curated.source_id
        # A pair of scored members is below the team floor, so only the larger team shows.
        assert [team.github_team for team in friction.teams] == expected_teams

    @parameterized.expand(
        [
            ("scored_author", "typical", 2, ["everyone"], [205, 204, 203, 202, 201]),
            ("login_in_other_case", "TYPICAL", 2, ["everyone"], [205, 204, 203, 202, 201]),
            ("below_the_minimum", "newcomer", None, ["everyone"], [401, 400]),
        ]
    )
    def test_detail(self, _name: str, author: str, rank: int | None, teams: list[str], numbers: list[int]) -> None:
        curated = _Curated([_row(pr) for pr in _population()], _MEMBERS)

        detail = build_author_friction_detail(curated=curated, author=author)  # type: ignore[arg-type]

        assert (detail.author.rank if detail.author else None) == rank
        # The author stays out of their own team baseline, so "pair" drops below two other members.
        assert [team.github_team for team in detail.teams] == teams
        assert [(pr.number, pr.title) for pr in detail.pull_requests] == [(n, f"PR {n}") for n in numbers]

    @parameterized.expand(
        [
            ("merged_in_window", _population(), "PostHog/posthog", 305, True, (2, 2)),
            ("not_in_window", _population(), "PostHog/posthog", 999, True, None),
            ("same_number_in_another_repository", _population(), "PostHog/posthog.com", 305, True, None),
            ("no_view_yet", None, "PostHog/posthog", 305, False, None),
        ]
    )
    def test_pull_request(
        self,
        _name: str,
        prs: list[PullRequestFriction] | None,
        repo: str,
        number: int,
        available: bool,
        counts: tuple[int, int] | None,
    ) -> None:
        curated = _Curated([_row(pr) for pr in prs] if prs is not None else None, _MEMBERS)

        detail = build_pull_request_friction(curated=curated, repo=repo, number=number)  # type: ignore[arg-type]

        assert detail.available is available
        breakdown = detail.pull_request
        assert (None if breakdown is None else (breakdown.master_red_count, breakdown.kickout_count)) == counts
        if breakdown is not None:
            # The PR page and the author page's top list must agree on a pull request's score.
            author_page = build_author_friction_detail(curated=curated, author="blocked")  # type: ignore[arg-type]
            listed = next(pr for pr in author_page.pull_requests if pr.number == number)
            assert breakdown.score == pytest.approx(listed.score)

    def test_pull_request_scores_when_nobody_has_enough_pull_requests(self) -> None:
        curated = _Curated([_row(_pr("newcomer", 700, master_red_count=2)), _row(_pr("other", 701))], _MEMBERS)

        detail = build_pull_request_friction(curated=curated, repo="PostHog/posthog", number=700)  # type: ignore[arg-type]

        assert detail.pull_request is not None
        assert detail.pull_request.score > 1
