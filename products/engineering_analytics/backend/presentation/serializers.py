"""DRF serializers for engineering_analytics.

Output-only serializers that turn the facade's frozen dataclasses into JSON via
``DataclassSerializer``. Field types are auto-derived from the contract types;
``help_text`` is added through ``Meta.extra_kwargs`` so it flows downstream into
the OpenAPI spec, generated TypeScript types, and the ``pr_lifecycle`` MCP tool
schema.
"""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import (
    Author,
    PRLifecycle,
    PRLifecycleEvent,
    PullRequest,
    RepoRef,
)


class RepoRefSerializer(DataclassSerializer):
    class Meta:
        dataclass = RepoRef
        extra_kwargs = {
            "provider": {"help_text": "Code host provider, e.g. 'github'."},
            "owner": {"help_text": "Repository owner or organization."},
            "name": {"help_text": "Repository name."},
        }


class AuthorSerializer(DataclassSerializer):
    class Meta:
        dataclass = Author
        extra_kwargs = {
            "handle": {"help_text": "Login handle of the pull request author."},
            "display_name": {"help_text": "Human-readable name; equals the handle in v1."},
            "avatar_url": {"help_text": "URL of the author's avatar image."},
            "is_bot": {"help_text": "True if the author is a bot (handle ends in [bot] or is a known bot)."},
        }


class PullRequestSerializer(DataclassSerializer):
    author = AuthorSerializer(help_text="The pull request author.")
    repo = RepoRefSerializer(help_text="Repository the pull request belongs to.")

    class Meta:
        dataclass = PullRequest
        extra_kwargs = {
            "id": {"help_text": "GitHub pull request id."},
            "number": {"help_text": "Pull request number within the repository."},
            "title": {"help_text": "Pull request title."},
            "state": {"help_text": "Derived state: 'open', 'closed', or 'merged'."},
            "is_draft": {"help_text": "True if the pull request is a draft."},
            "created_at": {"help_text": "When the pull request was opened."},
            "merged_at": {"help_text": "When the pull request was merged, or null.", "allow_null": True},
            "closed_at": {"help_text": "When the pull request was closed, or null.", "allow_null": True},
        }


class PRLifecycleEventSerializer(DataclassSerializer):
    class Meta:
        dataclass = PRLifecycleEvent
        extra_kwargs = {
            "kind": {"help_text": "Event kind: opened, ci_started, ci_finished, merged, or closed."},
            "at": {"help_text": "When the event occurred."},
            "detail": {
                "help_text": "Optional detail, e.g. workflow name and conclusion for CI events.",
                "allow_null": True,
            },
        }


class PRLifecycleSerializer(DataclassSerializer):
    pull_request = PullRequestSerializer(help_text="The pull request header.")
    events = PRLifecycleEventSerializer(many=True, help_text="Lifecycle events ordered by time.")

    class Meta:
        dataclass = PRLifecycle
        extra_kwargs = {
            "metric_quality": {
                "help_text": "Always 'partial' — CI events only; reviews and comments are not yet available.",
            },
        }
