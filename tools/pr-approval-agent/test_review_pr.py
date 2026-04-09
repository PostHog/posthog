"""Tests for review_pr pipeline debug summaries."""

import sys
import types
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_review_pr_module(monkeypatch, *, reviewer_class):
    gates_module = types.ModuleType("gates")
    gates_module.MAX_FILES = 100
    gates_module.MAX_LINES = 1000
    gates_module.assign_tier = lambda **kwargs: "T1-agent"
    gates_module.classify_files = lambda file_paths: {"categories": [], "top_dirs": []}
    gates_module.detect_deny_categories = lambda file_paths, title: []
    gates_module.detect_ownership = lambda file_paths, ownership_rules: {
        "team_count": 0,
        "teams": [],
        "cross_team": False,
    }
    gates_module.has_ci_workflow_changes = lambda file_paths: False
    gates_module.has_dependency_changes = lambda file_paths: False
    gates_module.is_allow_listed_only = lambda file_paths: False
    gates_module.parse_codeowners_soft = lambda path: []
    gates_module.parse_conventional_commit = lambda title: {"type": "fix", "scope": "ci"}
    gates_module.scope_breadth = lambda top_dirs: "single-area"
    gates_module.t1_risk_subclass = lambda **kwargs: "T1b-small"
    gates_module.test_only = lambda categories: False

    @dataclass
    class PRData:
        number: int
        repo: str
        title: str
        state: str
        draft: bool
        mergeable_state: str
        author: str
        labels: list[str]
        base_sha: str
        head_sha: str
        files: list[dict]
        reviews: list[dict]
        review_comments: list[dict]
        check_runs: list[dict]

        @property
        def file_paths(self) -> list[str]:
            return [f["filename"] for f in self.files]

        @property
        def has_new_files(self) -> bool:
            return any(f.get("status") == "A" for f in self.files)

        @property
        def lines_added(self) -> int:
            return sum(f["additions"] for f in self.files)

        @property
        def lines_deleted(self) -> int:
            return sum(f["deletions"] for f in self.files)

        @property
        def lines_total(self) -> int:
            return self.lines_added + self.lines_deleted

    github_module = types.ModuleType("github")
    github_module.PRData = PRData
    github_module.check_team_membership = lambda author, team_slug: False
    github_module.fetch_pr = lambda pr_number, repo, repo_root=None: None

    reviewer_module = types.ModuleType("reviewer")
    reviewer_module.Reviewer = reviewer_class

    monkeypatch.setitem(sys.modules, "gates", gates_module)
    monkeypatch.setitem(sys.modules, "github", github_module)
    monkeypatch.setitem(sys.modules, "reviewer", reviewer_module)

    review_pr_path = Path(__file__).with_name("review_pr.py")
    spec = spec_from_file_location("review_pr_under_test", review_pr_path)
    module = module_from_spec(spec)
    assert spec and spec.loader
    monkeypatch.setitem(sys.modules, "review_pr_under_test", module)
    spec.loader.exec_module(module)
    return module, PRData


def test_pipeline_surfaces_debug_summary_when_reviewer_retries_exhaust(monkeypatch) -> None:
    class Reviewer:
        def __init__(self, repo_root, *, verbose: bool = False):
            self.repo_root = repo_root
            self.verbose = verbose

        def review(self, pr, classification, gate_context):
            raise RuntimeError("connection refused")

    review_pr_module, pr_data_class = _load_review_pr_module(monkeypatch, reviewer_class=Reviewer)
    monkeypatch.setattr(review_pr_module.time, "sleep", lambda seconds: None)

    pipeline = review_pr_module.Pipeline(53958, "PostHog/posthog")
    pipeline.pr = pr_data_class(
        number=53958,
        repo="PostHog/posthog",
        title="fix(ci): fall back when stamphog instrumentation fails",
        state="OPEN",
        draft=False,
        mergeable_state="MERGEABLE",
        author="lucasheriques",
        labels=[],
        base_sha="base",
        head_sha="head",
        files=[{"filename": "tools/pr-approval-agent/reviewer.py", "additions": 10, "deletions": 2}],
        reviews=[],
        review_comments=[],
        check_runs=[],
    )
    pipeline.classification = {
        "tier": "T1-agent",
        "t1_subclass": "T1b-small",
        "breadth": "single-area",
        "commit_type": "fix",
    }
    pipeline.gate_results = []

    pipeline._llm_review("PENDING")

    assert pipeline.final_verdict == "ESCALATE"
    assert pipeline.reviewer_output["verdict"] == "ESCALATE"
    assert pipeline.reviewer_output["reasoning"] == "Review agent failed after 3 attempts — needs human review."
    assert pipeline.reviewer_output["issues"] == ["connection refused"]
    assert pipeline.reviewer_output["debug_summary"].startswith(
        "Reviewer failed before producing a verdict. error=RuntimeError: connection refused."
    )
