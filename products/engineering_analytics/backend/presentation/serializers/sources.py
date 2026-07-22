"""Payload for the GitHub source/repo picker."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import GitHubSource


class GitHubSourceSerializer(DataclassSerializer):
    class Meta:
        dataclass = GitHubSource
        extra_kwargs = {
            "id": {"help_text": "Source id — pass back as `source_id` (with `repo`) to read this repository."},
            "repo": {
                "help_text": "Repository as 'owner/name' — pass back as `repo` to scope to it. One entry per "
                "repository a source syncs; '' if unknown."
            },
            "prefix": {"help_text": "User-chosen warehouse table-name prefix for this source, or '' when none."},
            "synced": {
                "help_text": "Whether this repo has both pull_requests and workflow_runs synced (readable "
                "now). Default the picker to the first synced entry so its label matches the resolved repo."
            },
        }
