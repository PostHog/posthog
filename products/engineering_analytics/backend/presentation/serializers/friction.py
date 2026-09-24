"""Payloads for the friction read: every author's friction as a multiple of the typical author."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import (
    AuthorFriction,
    AuthorFrictionDetail,
    AuthorFrictionList,
    FrictionGroupShare,
    PullRequestFrictionItem,
    TeamFriction,
)


class FrictionGroupShareSerializer(DataclassSerializer):
    class Meta:
        dataclass = FrictionGroupShare
        extra_kwargs = {
            "group": {
                "help_text": "ci (red CI and CI waits), review (waiting for the first approval), queue (merge-queue "
                "time and kickouts), or rework (own failures and extra pushes)."
            },
            "score": {"help_text": "This group's part of the score, in the same 'x typical' unit. The parts add up."},
        }


class AuthorFrictionSerializer(DataclassSerializer):
    groups = FrictionGroupShareSerializer(many=True, help_text="The score split by the kind of friction.")

    class Meta:
        dataclass = AuthorFriction
        extra_kwargs = {
            "author": {"help_text": "GitHub login."},
            "avatar_url": {"help_text": "The author's GitHub avatar, or empty when the pull requests carry none."},
            "score": {
                "help_text": "Friction as a multiple of the typical author: 1.0 is typical, 2.0 is twice as much. "
                "Counts only what happened to the author, never how much or how fast they ship."
            },
            "pr_count": {"help_text": "The author's merged pull requests in the window."},
            "rank": {"help_text": "Position by friction in the repository, 1 is the most."},
            "rank_low": {
                "help_text": "Low end of the rank band: the 10th percentile rank over resamples of the author's "
                "pull requests, and never above rank."
            },
            "rank_high": {
                "help_text": "High end of the rank band: the 90th percentile rank over the same resamples, and "
                "never below rank."
            },
            "teams": {"help_text": "The author's GitHub teams. Empty when the membership table isn't synced."},
        }


class TeamFrictionSerializer(DataclassSerializer):
    class Meta:
        dataclass = TeamFriction
        extra_kwargs = {
            "github_team": {"help_text": "GitHub team slug."},
            "median_score": {"help_text": "The median friction of the team's scored members, in 'x typical' units."},
            "scored_author_count": {
                "help_text": "Members with enough merged pull requests to score. A team shows only above a floor, "
                "so one or two people never read as a team's figure."
            },
        }


class PullRequestFrictionItemSerializer(DataclassSerializer):
    groups = FrictionGroupShareSerializer(many=True, help_text="The pull request's friction split by kind.")

    class Meta:
        dataclass = PullRequestFrictionItem
        extra_kwargs = {
            "number": {"help_text": "Pull request number."},
            "repo_owner": {"help_text": "Repository owner."},
            "repo_name": {"help_text": "Repository name."},
            "title": {"help_text": "Pull request title, empty when the snapshot has none."},
            "score": {"help_text": "Friction as a multiple of the typical pull request in the repository."},
        }


class AuthorFrictionListSerializer(DataclassSerializer):
    items = AuthorFrictionSerializer(many=True, help_text="Authors by friction, most first.")
    teams = TeamFrictionSerializer(
        many=True, help_text="Teams with at least 3 scored members, by median member friction, most first."
    )

    class Meta:
        dataclass = AuthorFrictionList
        extra_kwargs = {
            "available": {
                "help_text": "False when the per-PR friction view does not exist yet: it needs a GitHub source "
                "with workflow runs, workflow jobs and pull requests synced."
            },
            "window_days": {"help_text": "Pull requests merged in this many days before the view last refreshed."},
            "ranked_author_count": {
                "help_text": "Authors with at least 3 merged pull requests, all ranked together. A team list "
                "keeps these repository-wide ranks."
            },
            "github_team": {"help_text": "The team the list is filtered to, or null for every author."},
            "has_membership_data": {
                "help_text": "False when the team membership table isn't synced, so a team filter matches nobody."
            },
        }


class AuthorFrictionDetailSerializer(DataclassSerializer):
    author = AuthorFrictionSerializer(
        allow_null=True, help_text="The author's score and rank. Null below 3 merged pull requests in the window."
    )
    teams = TeamFrictionSerializer(
        many=True,
        help_text="The author's teams without the author, each only with at least 2 other scored members.",
    )
    pull_requests = PullRequestFrictionItemSerializer(
        many=True, help_text="The author's pull requests that added the most friction, most first."
    )

    class Meta:
        dataclass = AuthorFrictionDetail
        extra_kwargs = {
            "available": {
                "help_text": "False when the per-PR friction view does not exist yet: it needs a GitHub source "
                "with workflow runs, workflow jobs and pull requests synced."
            },
            "window_days": {"help_text": "Pull requests merged in this many days before the view last refreshed."},
            "ranked_author_count": {"help_text": "Authors ranked in the repository: the denominator of rank."},
            "has_membership_data": {"help_text": "False when the team membership table isn't synced."},
            "pr_count": {"help_text": "The author's merged pull requests in the window."},
        }
