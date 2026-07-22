"""Serializers shared across domain modules, and their own leaves."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import CIFailureLogLine, CIJobFailureLog, RepoRef


class RepoRefSerializer(DataclassSerializer):
    class Meta:
        dataclass = RepoRef
        extra_kwargs = {
            "provider": {"help_text": "Code host provider, e.g. 'github'."},
            "owner": {"help_text": "Repository owner or organization."},
            "name": {"help_text": "Repository name."},
        }


class CIFailureLogLineSerializer(DataclassSerializer):
    class Meta:
        dataclass = CIFailureLogLine
        extra_kwargs = {
            "original_line": {
                "help_text": "1-based line number in the full pre-thinning job log, or null for a "
                "'... N lines omitted ...' marker. The gap between consecutive values is how many lines were elided.",
                "allow_null": True,
            },
            "text": {"help_text": "The log line text, or the omission-marker text."},
        }


class CIJobFailureLogSerializer(DataclassSerializer):
    lines = CIFailureLogLineSerializer(
        many=True, help_text="The thinned failure-log lines in original order, with omission markers."
    )

    class Meta:
        dataclass = CIJobFailureLog
        extra_kwargs = {
            "job_id": {"help_text": "GitHub Actions job id of the failed job."},
            "run_id": {"help_text": "Workflow run id the job belongs to."},
            "conclusion": {
                "help_text": "Job conclusion ('failure', 'timed_out', ...). Only failed jobs have logs.",
            },
            "branch": {"help_text": "Git branch the run was triggered on, or '' when unknown."},
            "original_total_lines": {
                "help_text": "Total lines in the full job log before thinning (the denominator for each line's "
                "original_line); 0 when unknown.",
            },
            "line_count": {"help_text": "Number of lines returned for this job (after the per-job cap)."},
            "truncated": {"help_text": "True when the job had more failure lines than the per-job cap."},
        }
