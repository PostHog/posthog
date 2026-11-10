import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest

import httpx
import requests
from anthropic import Anthropic, APITimeoutError

from products.knowledge_writer.backend.facade.contracts import MergeCheckReport
from products.knowledge_writer.backend.facade.enums import DocsChangeKind
from products.knowledge_writer.backend.logic.pull_requests import LINK_BACK_START
from products.knowledge_writer.backend.settings import DocsSource
from products.knowledge_writer.merge_check.check import MergeNotConfirmed, MergeNotOnDefaultBranch, run_merge_check
from products.knowledge_writer.merge_check.facts import (
    Audience,
    AudienceFact,
    DocImpact,
    DocImpactFact,
    MergeFacts,
    ReleaseState,
    ReleaseStateFact,
    YesNoFact,
)
from products.knowledge_writer.merge_check.judge import JudgeVerdict
from products.knowledge_writer.merge_check.sources import LandedChange

COMPONENT_PATH = "products/feature_flags/frontend/FlagBanner.tsx"
COMPONENT_CHUNK = f"diff --git a/{COMPONENT_PATH} b/{COMPONENT_PATH}\n-old\n+new\n"
SCRIPT_CHUNK = "diff --git a/bin/start b/bin/start\n-old\n+new\n"
GENERATED_CHUNK = "diff --git a/posthog/schema.py b/posthog/schema.py\n-old\n+new\n"
FLAGS_PATHS = [f"feature-flags/page-{number}" for number in range(200)]
FLAGS_PAGES = [f"https://posthog.com/docs/{path}" for path in FLAGS_PATHS]
INTERNAL_ONLY_DIFF = (
    "diff --git a/posthog/test/test_flags.py b/posthog/test/test_flags.py\n-old\n+new\n"
    "diff --git a/pnpm-lock.yaml b/pnpm-lock.yaml\n-old\n+new\n"
)
WRITER_LOGIN = "knowledge-writer[bot]"
DOCS_SOURCE = DocsSource(
    docs_repository="PostHog/posthog.com",
    sitemap_url="https://posthog.com/sitemap/sitemap-0.xml",
    docs_url_prefix="https://posthog.com/docs/",
)


def landed(commit_sha: str, pull_request_number: int = 7) -> LandedChange:
    return LandedChange(repository="PostHog/posthog", after=commit_sha, pull_request_number=pull_request_number)


class FakePostHogGitHub:
    def __init__(
        self,
        commit_sha: str,
        *,
        merged_commit_sha: str | None = None,
        comparison_with_default_branch: str = "behind",
        merge_diff: str = GENERATED_CHUNK + SCRIPT_CHUNK + COMPONENT_CHUNK,
        docs_page_paths: tuple[str, ...] = tuple(FLAGS_PATHS),
        docs_pull_requests: tuple[dict[str, object], ...] = (),
        docs_pull_request_comments: tuple[str, ...] = (),
    ) -> None:
        self.commit_sha = commit_sha
        self.merged_commit_sha = merged_commit_sha or commit_sha
        self.comparison_with_default_branch = comparison_with_default_branch
        self.merge_diff = merge_diff
        self.docs_page_paths = docs_page_paths
        self.docs_pull_requests = docs_pull_requests
        self.docs_pull_request_comments = docs_pull_request_comments

    def merged_pull_request(self) -> dict[str, object]:
        return {
            "number": 7,
            "title": "chore: drop legacy rollout",
            "html_url": "https://github.com/PostHog/posthog/pull/7",
            "merge_commit_sha": self.merged_commit_sha,
            "merged_at": "2026-10-27T00:00:00Z",
            "base": {"ref": "stack/parent-branch", "repo": {"default_branch": "master"}},
        }

    def api_request(self, method: str, path: str, **_options: object) -> requests.Response:
        if path.endswith("/pulls/7"):
            return github_response(json.dumps(self.merged_pull_request()))
        if path.endswith(f"/compare/master...{self.commit_sha}"):
            return github_response(json.dumps({"status": self.comparison_with_default_branch}))
        if path.endswith("/.gitattributes"):
            return github_response("# Generated code\nposthog/schema.py linguist-generated\n")
        if path.endswith(f"/commits/{self.commit_sha}"):
            return github_response(self.merge_diff)
        if path == "/repos/PostHog/posthog.com/git/trees/HEAD":
            tree = [{"path": f"contents/docs/{page_path}.mdx", "type": "blob"} for page_path in self.docs_page_paths]
            return github_response(json.dumps({"tree": tree, "truncated": False}))
        if path == "/repos/PostHog/posthog.com/pulls":
            return github_response(json.dumps(list(self.docs_pull_requests)))
        if path == "/repos/PostHog/posthog.com/issues/41/comments":
            return github_response(json.dumps([{"body": comment} for comment in self.docs_pull_request_comments]))
        if path.endswith("/releases"):
            return github_response("", status_code=404)
        raise AssertionError(f"unexpected GitHub request {path}")


def docs_pull_request(
    author_login: str,
    body: str,
    *,
    author_association: str = "NONE",
    updated_at: str = "2026-10-28T00:00:00Z",
    source_reference: str = "Follows https://github.com/PostHog/posthog/pull/7",
) -> dict[str, object]:
    return {
        "number": 41,
        "state": "open",
        "html_url": "https://github.com/PostHog/posthog.com/pull/41",
        "updated_at": updated_at,
        "user": {"login": author_login},
        "author_association": author_association,
        "head": {"ref": "docs/flags", "repo": {"full_name": "PostHog/posthog.com"}},
        "title": "Document the flag banner",
        "body": f"{body}\n{source_reference}",
    }


def check_merge(
    commit_sha: str, github: FakePostHogGitHub, anthropic_client: Anthropic, *, is_final_attempt: bool = False
) -> MergeCheckReport:
    return run_merge_check(
        landed(commit_sha),
        is_final_attempt=is_final_attempt,
        github=github,
        http=fake_sitemap(),
        anthropic_client=anthropic_client,
        source=DOCS_SOURCE,
        writer_login=WRITER_LOGIN,
    )


def github_response(body: str, status_code: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = body.encode()
    return response


def fake_sitemap() -> httpx.Client:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="".join(f"<loc>{url}</loc>" for url in FLAGS_PAGES))

    return httpx.Client(transport=httpx.MockTransport(respond))


def judge_with_parse(parse: Callable[..., object]) -> Anthropic:
    client = SimpleNamespace(messages=SimpleNamespace(parse=parse))
    client.with_options = lambda **_options: client
    return cast(Anthropic, client)


def merge_facts(
    release_state: ReleaseState = ReleaseState.GA,
    release_quote: str = "",
    *,
    rests_only_on_release_marker: bool = False,
) -> MergeFacts:
    return MergeFacts(
        release_state=ReleaseStateFact(
            value=release_state, quote=release_quote, rests_only_on_release_marker=rests_only_on_release_marker
        ),
        audience=AudienceFact(value=Audience.CUSTOMER, quote=""),
        doc_impact=DocImpactFact(value=DocImpact.CHANGED_BEHAVIOR, quote="drop legacy rollout"),
        generated_only=YesNoFact(value=False, quote=""),
        no_public_page_fits=YesNoFact(value=False, quote=""),
        changed_pages=[],
    )


def judge_recording(verdict: JudgeVerdict, judge_requests: list[dict], facts: MergeFacts | None = None) -> Anthropic:
    def parse(**request: object) -> object:
        if request["output_format"] is MergeFacts:
            return SimpleNamespace(stop_reason="end_turn", parsed_output=facts or merge_facts())
        judge_requests.append(request)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=verdict)

    return judge_with_parse(parse)


def judge_returning_malformed_output() -> Anthropic:
    def parse(**_request: object) -> object:
        return JudgeVerdict.model_validate({"needs_docs": "maybe"})

    return judge_with_parse(parse)


def test_merge_judged_on_non_generated_diff_yields_every_listed_sitemap_page_once() -> None:
    commit_sha = "a" * 40
    judge_requests: list[dict] = []
    verdict = JudgeVerdict(
        needs_docs=True,
        change_kind=DocsChangeKind.UPDATE,
        page_urls=[FLAGS_PATHS[-1], *FLAGS_PATHS[:3], FLAGS_PATHS[-1], "feature-flags/not-listed"],
        reason="new option",
    )

    report = check_merge(commit_sha, FakePostHogGitHub(commit_sha), judge_recording(verdict, judge_requests))

    judge_content = judge_requests[0]["messages"][0]["content"]
    assert "Docs pages:\n" + "\n".join(FLAGS_PATHS) + "\n\n<diff>" in judge_content
    assert judge_content.endswith(f"<diff>\n{SCRIPT_CHUNK}{COMPONENT_CHUNK}\n</diff>")
    assert (report.needs_docs, report.change_kind) == (True, DocsChangeKind.UPDATE)
    assert report.page_urls == (FLAGS_PAGES[-1], *FLAGS_PAGES[:3])
    assert (report.repository, report.pull_request_number) == ("PostHog/posthog", 7)
    assert [(row.criterion, row.value) for row in report.criteria] == [
        ("code_changed", "true"),
        ("knowledge_writer_docs_pr", "false"),
        ("other_docs_pr", "false"),
        ("not_editable_here", "0"),
        ("docs_version", "documented"),
        ("release_state", "ga"),
        ("audience", "customer"),
        ("doc_impact", "changed_behavior"),
        ("generated_only", "false"),
        ("no_public_page_fits", "false"),
        ("judge", "update"),
    ]


def test_update_naming_no_sitemap_page_becomes_create() -> None:
    commit_sha = "c" * 40
    verdict = JudgeVerdict(
        needs_docs=True, change_kind=DocsChangeKind.UPDATE, page_urls=["product-analytics/alerts"], reason="new option"
    )

    report = check_merge(commit_sha, FakePostHogGitHub(commit_sha), judge_recording(verdict, []))

    assert (report.needs_docs, report.change_kind, report.page_urls) == (True, DocsChangeKind.CREATE, ())


def test_sitemap_pages_without_a_docs_source_are_kept_from_the_judge() -> None:
    commit_sha = "d" * 40
    judge_requests: list[dict] = []
    verdict = JudgeVerdict(
        needs_docs=True, change_kind=DocsChangeKind.UPDATE, page_urls=[FLAGS_PATHS[-1]], reason="new option"
    )
    github = FakePostHogGitHub(commit_sha, docs_page_paths=tuple(FLAGS_PATHS[:150]))

    report = check_merge(commit_sha, github, judge_recording(verdict, judge_requests))

    judge_content = judge_requests[0]["messages"][0]["content"]
    assert FLAGS_PATHS[149] in judge_content and FLAGS_PATHS[-1] not in judge_content
    assert (report.change_kind, report.page_urls) == (DocsChangeKind.CREATE, ())
    assert ("not_editable_here", "50") in [(row.criterion, row.value) for row in report.criteria]


@pytest.mark.parametrize(
    "github_for, blocking_reason",
    [
        pytest.param(
            lambda commit_sha: FakePostHogGitHub(commit_sha, merge_diff=INTERNAL_ONLY_DIFF),
            "code_changed",
            id="tests_and_lockfile_only",
        ),
        pytest.param(
            lambda commit_sha: FakePostHogGitHub(
                commit_sha, docs_pull_requests=(docs_pull_request(WRITER_LOGIN, LINK_BACK_START),)
            ),
            "knowledge_writer_docs_pr",
            id="knowledge_writer_docs_pr_open",
        ),
        pytest.param(
            lambda commit_sha: FakePostHogGitHub(
                commit_sha,
                docs_pull_requests=(
                    docs_pull_request(
                        WRITER_LOGIN, LINK_BACK_START, updated_at="2026-09-01T00:00:00Z", source_reference=""
                    ),
                ),
                docs_pull_request_comments=("- https://github.com/PostHog/posthog/pull/7",),
            ),
            "knowledge_writer_docs_pr",
            id="stale_knowledge_writer_docs_pr_joined_by_comment",
        ),
    ],
)
def test_a_blocking_gate_records_no_docs_without_a_judge_call(
    github_for: Callable[[str], FakePostHogGitHub], blocking_reason: str
) -> None:
    commit_sha = "9" * 40
    judge_requests: list[dict] = []
    verdict = JudgeVerdict(needs_docs=True, change_kind=DocsChangeKind.UPDATE, page_urls=[], reason="new option")

    report = check_merge(commit_sha, github_for(commit_sha), judge_recording(verdict, judge_requests))

    assert (report.needs_docs, report.reason, judge_requests) == (False, blocking_reason, [])


@pytest.mark.parametrize(
    "facts, expected_reason, is_judged, low_confidence",
    [
        pytest.param(
            merge_facts(ReleaseState.FLAGGED_OR_UNRELEASED, "drop legacy rollout"),
            "release_state",
            False,
            False,
            id="quoted_flag_blocks",
        ),
        pytest.param(
            merge_facts(ReleaseState.FLAGGED_OR_UNRELEASED, "behind the beta flag"),
            "judge",
            True,
            True,
            id="unquoted_flag_falls_back_to_ga",
        ),
        pytest.param(
            merge_facts(ReleaseState.FLAGGED_OR_UNRELEASED, "e"),
            "judge",
            True,
            True,
            id="token_quote_falls_back_to_ga",
        ),
        pytest.param(
            merge_facts(ReleaseState.FLAGGED_OR_UNRELEASED, "drop legacy rollout", rests_only_on_release_marker=True),
            "judge",
            True,
            True,
            id="release_marker_alone_only_lowers_confidence",
        ),
    ],
)
def test_release_facts_gate_only_on_quoted_evidence(
    facts: MergeFacts, expected_reason: str, is_judged: bool, low_confidence: bool
) -> None:
    commit_sha = "7" * 40
    judge_requests: list[dict] = []
    verdict = JudgeVerdict(needs_docs=True, change_kind=DocsChangeKind.CREATE, page_urls=[], reason="new option")

    report = check_merge(commit_sha, FakePostHogGitHub(commit_sha), judge_recording(verdict, judge_requests, facts))

    assert (report.reason, bool(judge_requests), report.low_confidence) == (expected_reason, is_judged, low_confidence)


def test_a_failed_fact_call_retries_then_judges_with_low_confidence_on_the_final_attempt() -> None:
    commit_sha = "6" * 40
    judge_requests: list[dict] = []
    verdict = JudgeVerdict(needs_docs=True, change_kind=DocsChangeKind.CREATE, page_urls=[], reason="new option")

    def parse(**request: object) -> object:
        if request["output_format"] is MergeFacts:
            raise APITimeoutError(request=httpx.Request("POST", "https://gateway.example.com"))
        judge_requests.append(request)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=verdict)

    with pytest.raises(APITimeoutError):
        check_merge(commit_sha, FakePostHogGitHub(commit_sha), judge_with_parse(parse))
    report = check_merge(commit_sha, FakePostHogGitHub(commit_sha), judge_with_parse(parse), is_final_attempt=True)

    assert (report.needs_docs, report.low_confidence, len(judge_requests)) == (True, True, 1)


@pytest.mark.parametrize(
    "author_association, change_kind",
    [
        pytest.param("MEMBER", DocsChangeKind.REVIEW_EXISTING, id="member"),
        pytest.param("NONE", DocsChangeKind.UPDATE, id="unmerged_outsider_ignored"),
    ],
)
def test_a_docs_pull_request_from_a_trusted_person_asks_to_review_it(
    author_association: str, change_kind: DocsChangeKind
) -> None:
    commit_sha = "8" * 40
    person_docs_pull_request = docs_pull_request("docs-person", "", author_association=author_association)
    verdict = JudgeVerdict(
        needs_docs=True, change_kind=DocsChangeKind.UPDATE, page_urls=[FLAGS_PATHS[0]], reason="new option"
    )
    github = FakePostHogGitHub(commit_sha, docs_pull_requests=(person_docs_pull_request,))

    report = check_merge(commit_sha, github, judge_recording(verdict, []))

    assert (report.needs_docs, report.change_kind, report.page_urls) == (True, change_kind, (FLAGS_PAGES[0],))
    assert (str(person_docs_pull_request["html_url"]) in report.evidence) == (
        change_kind == DocsChangeKind.REVIEW_EXISTING
    )


def test_malformed_judge_output_declines_instead_of_raising() -> None:
    commit_sha = "b" * 40

    report = check_merge(commit_sha, FakePostHogGitHub(commit_sha), judge_returning_malformed_output())

    assert (report.needs_docs, report.reason) == (False, "judge_declined")


def test_a_pull_request_naming_another_merge_commit_is_retried_then_recorded_without_a_judge_call() -> None:
    commit_sha = "e" * 40
    github = FakePostHogGitHub(commit_sha, merged_commit_sha="d" * 40)

    with pytest.raises(MergeNotConfirmed):
        check_merge(commit_sha, github, judge_returning_malformed_output())
    report = check_merge(commit_sha, github, judge_returning_malformed_output(), is_final_attempt=True)

    assert (report.needs_docs, report.reason) == (False, "no_pull_request")


@pytest.mark.parametrize("comparison_with_default_branch", ["ahead", "diverged"])
def test_a_merge_into_a_branch_that_never_reached_the_default_branch_is_retried_then_recorded(
    comparison_with_default_branch: str,
) -> None:
    commit_sha = "f" * 40
    github = FakePostHogGitHub(commit_sha, comparison_with_default_branch=comparison_with_default_branch)

    with pytest.raises(MergeNotOnDefaultBranch):
        check_merge(commit_sha, github, judge_returning_malformed_output())
    report = check_merge(commit_sha, github, judge_returning_malformed_output(), is_final_attempt=True)

    assert (report.needs_docs, report.reason) == (False, "not_on_default_branch")
