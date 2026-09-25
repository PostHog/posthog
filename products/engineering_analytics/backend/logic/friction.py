"""Friction scores: how much the dev loop put each author through, as a multiple of the typical author.

A friction score counts only what happened to the author: failures they did not cause and re-runs that
failed again, waits on reviewers, the merge queue, and their own rework. It is a mean per pull request, so
shipping more or faster does not raise it (SPEC §2).

Every figure comes from the per-PR friction view (``views/pr_friction.py``). Each metric applies a curve
to each pull request, then an author's value is the mean over their pull requests, pulled toward the
repository mean with ``SHRINKAGE`` pseudo pull requests so that a handful of pull requests cannot put an
author at either end. Each value divides by the typical author's value, and the weights add the ratios
into one score where 1.0 is typical.

The weights are a choice, not a fit to this data: a simulation showed that equal weights inside judged
pain groups rank authors about as well as the true weights would, and paired comparisons of friction set
the group weights. Change them only with a new round of those comparisons.
"""

import math
import random
import statistics
from collections.abc import Callable
from dataclasses import dataclass

from posthog.hogql import ast
from posthog.hogql.errors import QueryError

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import (
    AuthorFriction,
    AuthorFrictionList,
    FrictionGroup,
    FrictionGroupShare,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.views import pr_friction

SHRINKAGE = 5
MIN_PULL_REQUESTS = 3
# Causes the author did not create cost a triage tax on top of the wait itself.
EXTERNAL_CAUSE_MULTIPLIER = 1.5
GROUP_WEIGHTS: dict[FrictionGroup, float] = {
    FrictionGroup.QUEUE: 40,
    FrictionGroup.REVIEW: 25,
    FrictionGroup.CI: 20,
    FrictionGroup.REWORK: 15,
}
# CI time below this per push, and merge-queue time below its own threshold, is the normal cost of a push.
CI_WAIT_FREE_SECONDS = 10 * 60
QUEUE_FREE_SECONDS = 30 * 60
APPROVAL_WAIT_REFERENCE_HOURS = 8
APPROVAL_SLOW_HOURS = 24
BOOTSTRAP_ROUNDS = 20
_BOOTSTRAP_SEED = 20260924


@dataclass(frozen=True, kw_only=True)
class PullRequestFriction:
    """One row of the per-PR friction view."""

    number: int
    author: str
    author_avatar_url: str
    push_count: int
    flake_red_count: int
    master_red_count: int
    unknown_red_count: int
    own_red_count: int
    futile_rerun_count: int
    ci_wait_seconds: tuple[float, ...]
    first_approval_wait_seconds: float | None
    pushes_after_approval: int | None
    queue_seconds: float | None
    kickout_count: int | None


def _approval_hours(pr: PullRequestFriction) -> float | None:
    if pr.first_approval_wait_seconds is None:
        return None
    return pr.first_approval_wait_seconds / 3600


def _log_approval_wait(pr: PullRequestFriction) -> float | None:
    hours = _approval_hours(pr)
    return None if hours is None else math.log1p(hours / APPROVAL_WAIT_REFERENCE_HOURS)


def _slow_approval(pr: PullRequestFriction) -> float | None:
    hours = _approval_hours(pr)
    return None if hours is None else float(hours >= APPROVAL_SLOW_HOURS)


def _ci_wait_minutes(pr: PullRequestFriction) -> float:
    return sum(max(0.0, seconds - CI_WAIT_FREE_SECONDS) for seconds in pr.ci_wait_seconds) / 60


def _queue_minutes(pr: PullRequestFriction) -> float:
    # A pull request that never entered the queue met no queue friction, so it still counts, as zero.
    return max(0.0, (pr.queue_seconds or 0.0) - QUEUE_FREE_SECONDS) / 60


def _optional(value: int | None) -> float | None:
    return None if value is None else float(value)


@dataclass(frozen=True, kw_only=True)
class FrictionMetric:
    key: str
    group: FrictionGroup
    weight: float
    external: bool
    # The metric's value for one pull request, curve applied. None means the pull request has no value.
    value: Callable[[PullRequestFriction], float | None]


METRICS: tuple[FrictionMetric, ...] = (
    # Each red stretch counts once, whatever its length: a red pull request left alone hardly affects anyone.
    FrictionMetric(
        key="flake_red", group=FrictionGroup.CI, weight=1, external=True, value=lambda pr: pr.flake_red_count
    ),
    FrictionMetric(
        key="master_red", group=FrictionGroup.CI, weight=1, external=True, value=lambda pr: pr.master_red_count
    ),
    FrictionMetric(
        key="unknown_red", group=FrictionGroup.CI, weight=0.5, external=False, value=lambda pr: pr.unknown_red_count
    ),
    FrictionMetric(key="ci_wait", group=FrictionGroup.CI, weight=1, external=False, value=_ci_wait_minutes),
    FrictionMetric(
        key="futile_reruns", group=FrictionGroup.CI, weight=1.5, external=True, value=lambda pr: pr.futile_rerun_count
    ),
    FrictionMetric(
        key="first_approval_wait", group=FrictionGroup.REVIEW, weight=1, external=False, value=_log_approval_wait
    ),
    FrictionMetric(
        key="first_approval_over_a_day", group=FrictionGroup.REVIEW, weight=1, external=False, value=_slow_approval
    ),
    FrictionMetric(key="queue_time", group=FrictionGroup.QUEUE, weight=1, external=False, value=_queue_minutes),
    FrictionMetric(
        key="kickouts",
        group=FrictionGroup.QUEUE,
        weight=1.5,
        external=True,
        value=lambda pr: pr.kickout_count or 0,
    ),
    FrictionMetric(
        key="own_red", group=FrictionGroup.REWORK, weight=1, external=False, value=lambda pr: pr.own_red_count
    ),
    FrictionMetric(
        key="extra_pushes",
        group=FrictionGroup.REWORK,
        weight=0.5,
        external=False,
        value=lambda pr: max(0, pr.push_count - 1),
    ),
    FrictionMetric(
        key="pushes_after_approval",
        group=FrictionGroup.REWORK,
        weight=1,
        external=False,
        value=lambda pr: _optional(pr.pushes_after_approval),
    ),
)


def effective_weights() -> list[float]:
    """Each metric's share of the whole score: its group's share, split by the weights inside the group."""
    group_total = sum(GROUP_WEIGHTS.values())
    inner = [metric.weight * (EXTERNAL_CAUSE_MULTIPLIER if metric.external else 1) for metric in METRICS]
    inner_totals = {
        group: sum(w for metric, w in zip(METRICS, inner) if metric.group == group) for group in GROUP_WEIGHTS
    }
    return [
        GROUP_WEIGHTS[metric.group] / group_total * w / inner_totals[metric.group] if inner_totals[metric.group] else 0
        for metric, w in zip(METRICS, inner)
    ]


@dataclass(frozen=True, kw_only=True)
class _AuthorScore:
    author: str
    score: float
    groups: dict[FrictionGroup, float]
    pr_count: int


@frozen
class _RankBand:
    low: int
    high: int


class FrictionScorer:
    """Scores every author with at least ``MIN_PULL_REQUESTS`` pull requests against each other."""

    def __init__(self, pull_requests: list[PullRequestFriction]) -> None:
        by_author: dict[str, list[PullRequestFriction]] = {}
        for pr in pull_requests:
            by_author.setdefault(pr.author, []).append(pr)
        self._authors = sorted(author for author, prs in by_author.items() if len(prs) >= MIN_PULL_REQUESTS)
        self._avatars = {
            author: next((pr.author_avatar_url for pr in reversed(prs) if pr.author_avatar_url), "")
            for author, prs in by_author.items()
        }
        self._weights = effective_weights()
        # values[author][metric] holds the curve value of each of the author's pull requests.
        self._values = {
            author: [[metric.value(pr) for pr in by_author[author]] for metric in METRICS] for author in self._authors
        }

    def _score(self, values: dict[str, list[list[float | None]]]) -> list[_AuthorScore]:
        present = {
            author: [[v for v in metric_values if v is not None] for metric_values in author_values]
            for author, author_values in values.items()
        }
        pooled = []
        for m in range(len(METRICS)):
            everything = [v for author_values in present.values() for v in author_values[m]]
            pooled.append(statistics.fmean(everything) if everything else 0.0)
        shrunk = {
            author: [
                (sum(author_values[m]) + SHRINKAGE * pooled[m]) / (len(author_values[m]) + SHRINKAGE)
                for m in range(len(METRICS))
            ]
            for author, author_values in present.items()
        }
        typical = [statistics.fmean(s[m] for s in shrunk.values()) if shrunk else 0.0 for m in range(len(METRICS))]
        # A metric nobody meets (a repository without a merge queue) passes its weight on to the others,
        # so the typical author stays at 1.0.
        weight_in_use = sum(w for m, w in enumerate(self._weights) if typical[m] > 0)
        scores = []
        for author, author_shrunk in shrunk.items():
            groups = dict.fromkeys(GROUP_WEIGHTS, 0.0)
            for m, metric in enumerate(METRICS):
                if typical[m] > 0:
                    groups[metric.group] += self._weights[m] / weight_in_use * author_shrunk[m] / typical[m]
            scores.append(
                _AuthorScore(author=author, score=sum(groups.values()), groups=groups, pr_count=len(values[author][0]))
            )
        return scores

    def _ranks(self, scores: list[_AuthorScore]) -> dict[str, int]:
        ordered = sorted(scores, key=lambda s: (-s.score, s.author))
        return {s.author: rank for rank, s in enumerate(ordered, start=1)}

    def _rank_bands(self) -> dict[str, _RankBand]:
        """The 10th to 90th percentile rank over bootstrap resamples of each author's pull requests."""
        rng = random.Random(_BOOTSTRAP_SEED)
        samples: dict[str, list[int]] = {author: [] for author in self._authors}
        for _ in range(BOOTSTRAP_ROUNDS):
            resampled = {}
            for author, author_values in self._values.items():
                count = len(author_values[0])
                picks = [rng.randrange(count) for _ in range(count)]
                resampled[author] = [[metric_values[i] for i in picks] for metric_values in author_values]
            for author, rank in self._ranks(self._score(resampled)).items():
                samples[author].append(rank)
        bands: dict[str, _RankBand] = {}
        for author, ranks in samples.items():
            deciles = statistics.quantiles(sorted(ranks), n=10, method="inclusive")
            bands[author] = _RankBand(low=math.floor(deciles[0]), high=math.ceil(deciles[-1]))
        return bands

    def score(self) -> list[AuthorFriction]:
        """Every scored author, most friction first."""
        if not self._authors:
            return []
        scores = self._score(self._values)
        ranks = self._ranks(scores)
        bands = self._rank_bands()
        return sorted(
            (
                AuthorFriction(
                    author=s.author,
                    avatar_url=self._avatars[s.author],
                    score=s.score,
                    groups=[FrictionGroupShare(group=group, score=value) for group, value in s.groups.items()],
                    pr_count=s.pr_count,
                    rank=ranks[s.author],
                    rank_low=min(bands[s.author].low, ranks[s.author]),
                    rank_high=max(bands[s.author].high, ranks[s.author]),
                )
                for s in scores
            ),
            key=lambda item: item.rank,
        )


_FRICTION_SELECT = f"""
    SELECT number, author, author_avatar_url, push_count, flake_red_count, master_red_count, unknown_red_count, own_red_count,
        futile_rerun_count, ci_wait_seconds, first_approval_wait_seconds, pushes_after_approval, queue_seconds,
        kickout_count
    FROM {pr_friction.VIEW_NAME}
    WHERE NOT is_bot AND author != '' AND __REPO__
"""

_TEAM_MEMBERS_SELECT = """
    SELECT DISTINCT member_handle FROM __MEMBERS_SOURCE__ AS m WHERE team_slug = {team}
"""


def _query_pull_requests(curated: CuratedGitHubSource) -> list[PullRequestFriction] | None:
    """The view's rows for the curated source's repository, or None when the team has no friction view.

    The view unions every GitHub source of the team, so the read keeps to the one source the caller is
    authorized for. A legacy single-repo source has no repository name, so the source id is the filter
    that always holds."""
    placeholders: dict[str, ast.Expr] = {"source_id": ast.Constant(value=curated.source_id)}
    repo_filter = "source_id = {source_id}"
    if "/" in curated.repository:
        owner, name = curated.repository.split("/", 1)
        # A source can store its repositories lowercased, while the view keeps GitHub's casing.
        repo_filter += " AND lower(repo_owner) = lower({repo_owner}) AND lower(repo_name) = lower({repo_name})"
        placeholders |= {"repo_owner": ast.Constant(value=owner), "repo_name": ast.Constant(value=name)}
    try:
        rows = curated.run_paged(
            _FRICTION_SELECT.replace("__REPO__", repo_filter),
            # A multi-repo source read without a repository keeps several repositories under one source id,
            # and their pull request numbers collide, so the page key carries the repository too.
            page_key=(("repo_owner", 1), ("repo_name", 2), ("number", 0)),
            query_type="engineering_analytics.author_friction",
            placeholders=placeholders,
        )
    except QueryError as exc:
        if f"Unknown table `{pr_friction.VIEW_NAME}`" in str(exc):
            return None
        raise
    return [
        PullRequestFriction(
            number=int(number),
            author=author,
            author_avatar_url=avatar_url or "",
            push_count=int(push_count),
            flake_red_count=int(flake),
            master_red_count=int(master),
            unknown_red_count=int(unknown),
            own_red_count=int(own),
            futile_rerun_count=int(futile),
            ci_wait_seconds=tuple(float(s) for s in ci_wait or ()),
            first_approval_wait_seconds=None if approval is None else float(approval),
            pushes_after_approval=None if after_approval is None else int(after_approval),
            queue_seconds=None if queue is None else float(queue),
            kickout_count=None if kickouts is None else int(kickouts),
        )
        for (
            number,
            author,
            avatar_url,
            push_count,
            flake,
            master,
            unknown,
            own,
            futile,
            ci_wait,
            approval,
            after_approval,
            queue,
            kickouts,
        ) in rows
    ]


def _query_team_members(curated: CuratedGitHubSource, github_team: str) -> set[str] | None:
    members_source = curated.members_source()
    if members_source is None:
        return None
    response = curated.run(
        _TEAM_MEMBERS_SELECT.replace("__MEMBERS_SOURCE__", members_source),
        query_type="engineering_analytics.author_friction_team_members",
        placeholders={"team": ast.Constant(value=github_team)},
    )
    return {handle for (handle,) in response.results or []}


def build_author_friction(*, curated: CuratedGitHubSource, github_team: str | None = None) -> AuthorFrictionList:
    """Every author's friction over the view's window, most first. A team keeps the repository-wide
    scores and ranks and lists only its members, so a member's figures read the same on every page."""
    window_days = pr_friction.FRICTION_WINDOW.days
    has_membership_data = curated.members_source() is not None
    pull_requests = _query_pull_requests(curated)
    if pull_requests is None:
        return AuthorFrictionList(
            available=False,
            window_days=window_days,
            ranked_author_count=0,
            github_team=github_team,
            has_membership_data=has_membership_data,
            items=[],
        )
    items = FrictionScorer(pull_requests).score()
    ranked_author_count = len(items)
    if github_team:
        members = _query_team_members(curated, github_team) or set()
        items = [item for item in items if item.author in members]
    return AuthorFrictionList(
        available=True,
        window_days=window_days,
        ranked_author_count=ranked_author_count,
        github_team=github_team,
        has_membership_data=has_membership_data,
        items=items,
    )
