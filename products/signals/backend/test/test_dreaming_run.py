from unittest.mock import MagicMock

from products.signals.backend.temporal.dreaming.cleanup_content import (
    build_cleanup_edits,
    render_cleanup_file,
    render_pr_body,
)
from products.signals.backend.temporal.dreaming.instrumentation_gaps import (
    InstrumentationGap,
    InstrumentationKind,
    PullRequestGaps,
)
from products.signals.backend.temporal.dreaming.run import run_instrumentation_cleanup


def _pr_gaps() -> list[PullRequestGaps]:
    return [
        PullRequestGaps(
            pr_number=5,
            pr_title="add checkout",
            gaps=(
                InstrumentationGap(
                    kind=InstrumentationKind.PRODUCT_ANALYTICS,
                    file_path="app/views.py",
                    line_hint="def checkout_view(request):",
                    rationale="new surface, no capture",
                ),
            ),
        )
    ]


class TestCleanupContent:
    def test_render_file_includes_counts_and_findings(self):
        content = render_cleanup_file(_pr_gaps())
        assert "1" in content
        assert "#5" in content
        assert "app/views.py" in content

    def test_render_pr_body_resurfaces_findings(self):
        body = render_pr_body(_pr_gaps())
        assert "Dreaming Agent" in body
        assert "app/views.py" in body

    def test_build_edits_empty_when_no_gaps(self):
        assert build_cleanup_edits([]) == []

    def test_build_edits_single_consolidated_file(self):
        edits = build_cleanup_edits(_pr_gaps())
        assert len(edits) == 1
        assert edits[0].path.endswith(".md")


def _diff(*lines: str) -> str:
    return "\n".join(f"+{line}" for line in lines)


class TestRunInstrumentationCleanup:
    def _github_with_merged_pr(self, files: dict) -> MagicMock:
        github = MagicMock()
        github.list_merged_pull_requests_since.return_value = {
            "success": True,
            "pull_requests": [
                {"number": 5, "title": "add checkout", "url": "u", "merged_at": "2026-06-19T01:00:00Z", "author": "a"}
            ],
        }
        github.get_pull_request_files.return_value = {
            "success": True,
            "files": [{"filename": name, "patch": patch} for name, patch in files.items()],
        }
        github.list_pull_requests.return_value = {"success": True, "pull_requests": []}
        github.get_branch_info.return_value = {"success": True, "exists": False}
        github.create_branch.return_value = {"success": True}
        github.update_file.return_value = {"success": True}
        github.create_pull_request.return_value = {"success": True, "pr_number": 9, "pr_url": "p", "state": "open"}
        github.add_labels_to_issue.return_value = {"success": True}
        return github

    def test_detects_gap_and_creates_pr(self):
        github = self._github_with_merged_pr(
            {"app/views.py": _diff("def submit_view(request):", "    return render()")}
        )

        result = run_instrumentation_cleanup(github, "repo", since_iso="2026-06-18T00:00:00Z")

        assert result.prs_inspected == 1
        assert result.gaps_detected == 1
        assert result.pr_action == "created"
        assert result.pr_number == 9

    def test_clean_prs_produce_noop(self):
        github = self._github_with_merged_pr(
            {"app/views.py": _diff("def submit_view(request):", "    posthog.capture('x')")}
        )

        result = run_instrumentation_cleanup(github, "repo", since_iso="2026-06-18T00:00:00Z")

        assert result.gaps_detected == 0
        assert result.pr_action == "noop"
        github.create_pull_request.assert_not_called()

    def test_no_merged_prs_is_noop(self):
        github = MagicMock()
        github.list_merged_pull_requests_since.return_value = {"success": True, "pull_requests": []}

        result = run_instrumentation_cleanup(github, "repo", since_iso="2026-06-18T00:00:00Z")

        assert result.prs_inspected == 0
        assert result.pr_action == "noop"
