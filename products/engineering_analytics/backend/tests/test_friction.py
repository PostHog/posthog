import statistics
from types import SimpleNamespace
from typing import Any

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.errors import QueryError

from products.engineering_analytics.backend.logic.friction import (
    MIN_PULL_REQUESTS,
    FrictionScorer,
    PullRequestFriction,
    build_author_friction,
)


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
    return PullRequestFriction(number=number, author=author, author_avatar_url="", **values)


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

    def __init__(self, rows: list[tuple] | None, members: list[str] | None) -> None:
        self._rows = rows
        self._members = members
        self.friction_placeholders: dict[str, Any] = {}

    def members_source(self) -> str | None:
        return None if self._members is None else "(SELECT 1)"

    def run_paged(self, sql: str, **kwargs: Any) -> list[tuple]:
        self.friction_placeholders = kwargs["placeholders"]
        if self._rows is None:
            raise QueryError("Unknown table `engineering_analytics_pr_friction`.")
        return self._rows

    def run(self, sql: str, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(results=[(member,) for member in self._members or []])


class TestFrictionScore(SimpleTestCase):
    def test_scores_order_experiences_around_the_typical_author(self) -> None:
        items = FrictionScorer(_population()).score()

        assert [item.author for item in items] == ["blocked", "typical", "calm"]
        assert statistics.fmean(item.score for item in items) == pytest.approx(1.0)
        for item in items:
            assert sum(share.score for share in item.groups) == pytest.approx(item.score)
            assert item.rank_low <= item.rank <= item.rank_high

    @parameterized.expand(
        [
            ("no_view_yet", None, ["typical"], None, False, []),
            ("whole_repository", _population(), None, None, True, [("blocked", 1), ("typical", 2), ("calm", 3)]),
            (
                "team_keeps_repository_ranks",
                _population(),
                ["typical", "calm"],
                "team-devex",
                True,
                [("typical", 2), ("calm", 3)],
            ),
        ]
    )
    def test_read(
        self,
        _name: str,
        prs: list[PullRequestFriction] | None,
        members: list[str] | None,
        github_team: str | None,
        available: bool,
        expected: list[tuple[str, int]],
    ) -> None:
        curated = _Curated([_row(pr) for pr in prs] if prs is not None else None, members)

        friction = build_author_friction(curated=curated, github_team=github_team)  # type: ignore[arg-type]

        assert friction.available is available
        assert [(item.author, item.rank) for item in friction.items] == expected
        # The view unions every source of the team, so the read must keep to its own.
        assert curated.friction_placeholders["source_id"].value == curated.source_id
