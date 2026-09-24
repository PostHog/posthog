"""Payloads for the friction read: every author's friction as a multiple of the typical author."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import (
    AuthorFriction,
    AuthorFrictionList,
    FrictionGroupShare,
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
        }


class AuthorFrictionListSerializer(DataclassSerializer):
    items = AuthorFrictionSerializer(many=True, help_text="Authors by friction, most first.")

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
