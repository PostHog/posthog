from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import (
    ApprovalRevertOutcome,
    AuthorshipRevertOutcome,
    RevertedPullRequest,
    RevertOutcomes,
)

_AUTHORSHIP_HELP = (
    "How the pull request was authored: 'bot' for a bot account, 'agent_context' when a person opened it and the "
    "description's Agent context section names a tool and model, 'no_agent_context' otherwise. A pull request "
    "without the section can still be agent-assisted."
)
_APPROVAL_HELP = (
    "Who approved the pull request before it merged: 'human' when at least one person approved, 'automated_only' "
    "when every approval came from a bot account, 'none' when no approval was recorded. An approval bot may approve "
    "only the pull requests its risk policy allows, so the 'automated_only' share reflects that selection as well as "
    "the effect of the approval."
)
_MERGED_HELP = "Pull requests merged in the window, excluding pull requests that are themselves reverts."
_REVERTED_HELP = (
    "How many of those pull requests a later merged revert names in its description. A recent merge can still be "
    "reverted, so this count can grow."
)
_SHARE_HELP = "reverted_pr_count divided by merged_pr_count. Null when nothing merged."


class AuthorshipRevertOutcomeSerializer(DataclassSerializer):
    class Meta:
        dataclass = AuthorshipRevertOutcome
        extra_kwargs = {
            "authorship": {"help_text": _AUTHORSHIP_HELP},
            "merged_pr_count": {"help_text": _MERGED_HELP},
            "reverted_pr_count": {"help_text": _REVERTED_HELP},
            "reverted_share": {"help_text": _SHARE_HELP, "allow_null": True},
        }


class ApprovalRevertOutcomeSerializer(DataclassSerializer):
    class Meta:
        dataclass = ApprovalRevertOutcome
        extra_kwargs = {
            "approval": {"help_text": _APPROVAL_HELP},
            "merged_pr_count": {"help_text": _MERGED_HELP},
            "reverted_pr_count": {"help_text": _REVERTED_HELP},
            "reverted_share": {"help_text": _SHARE_HELP, "allow_null": True},
        }


class RevertedPullRequestSerializer(DataclassSerializer):
    class Meta:
        dataclass = RevertedPullRequest
        extra_kwargs = {
            "number": {"help_text": "Number of the pull request that was reverted."},
            "title": {"help_text": "Title of the reverted pull request."},
            "merged_at": {"help_text": "When the reverted pull request merged."},
            "authorship": {"help_text": _AUTHORSHIP_HELP},
            "approval": {
                "help_text": _APPROVAL_HELP + " Null when the reviews table is not synced.",
                "allow_null": True,
            },
            "reverting_pr_number": {"help_text": "Number of the earliest merged pull request that reverted it."},
            "reverted_at": {"help_text": "When that reverting pull request merged."},
            "merge_to_revert_seconds": {"help_text": "Seconds from the merge to the merge of its revert."},
        }


class RevertOutcomesSerializer(DataclassSerializer):
    by_authorship = AuthorshipRevertOutcomeSerializer(
        many=True,
        help_text="One entry per authorship value, including values with no merges. Empty when "
        "body_data_available is false.",
    )
    by_approval = ApprovalRevertOutcomeSerializer(
        many=True,
        help_text="One entry per approval value, including values with no merges. Empty when "
        "body_data_available or review_data_available is false.",
    )
    reverted_pull_requests = RevertedPullRequestSerializer(
        many=True,
        help_text="The reverted pull requests, most recently reverted first, capped at limit.",
    )

    class Meta:
        dataclass = RevertOutcomes
        extra_kwargs = {
            "merged_pr_count": {"help_text": _MERGED_HELP},
            "reverted_pr_count": {
                "help_text": _REVERTED_HELP + " Null when body_data_available is false.",
                "allow_null": True,
            },
            "reverted_share": {
                "help_text": _SHARE_HELP + " Null when body_data_available is false.",
                "allow_null": True,
            },
            "body_data_available": {
                "help_text": "False when the synced pull requests table has no description column. A revert is "
                "linked to the change it undid through the revert's description, so no revert can be linked.",
            },
            "review_data_available": {
                "help_text": "False when the reviews table is not synced for the selected repository.",
            },
            "truncated": {"help_text": "True when more pull requests were reverted than reverted_pull_requests holds."},
            "limit": {"help_text": "Maximum number of entries in reverted_pull_requests."},
        }
