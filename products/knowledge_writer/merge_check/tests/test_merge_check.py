import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import requests
from anthropic import Anthropic

from products.knowledge_writer.backend.facade.enums import DocsChangeKind
from products.knowledge_writer.merge_check.check import run_merge_check
from products.knowledge_writer.merge_check.judge import JudgeVerdict
from products.knowledge_writer.merge_check.sources import MergeSubject

COMPONENT_PATH = "products/feature_flags/frontend/FlagBanner.tsx"
COMPONENT_CHUNK = f"diff --git a/{COMPONENT_PATH} b/{COMPONENT_PATH}\n-old\n+new\n"
SCRIPT_CHUNK = "diff --git a/bin/start b/bin/start\n-old\n+new\n"
GENERATED_CHUNK = "diff --git a/posthog/schema.py b/posthog/schema.py\n-old\n+new\n"
FLAGS_PATHS = [f"feature-flags/page-{number}" for number in range(4)]
FLAGS_PAGES = [f"https://posthog.com/docs/{path}" for path in FLAGS_PATHS]
DOCS_QUERY = "feature flag banner rollout option"


class FakePostHogGitHub:
    def __init__(self, commit_sha: str, published_page_paths: tuple[str, ...] = ()) -> None:
        self.commit_sha = commit_sha
        self.published_page_paths = published_page_paths
        self.requested_paths: list[str] = []

    def api_request(self, method: str, path: str, **_options: object) -> requests.Response:
        self.requested_paths.append(path)
        pull = {
            "number": 7,
            "title": "chore: drop legacy rollout",
            "html_url": "https://github.com/PostHog/posthog/pull/7",
            "merge_commit_sha": self.commit_sha,
            "merged_at": "2026-10-27T00:00:00Z",
            "base": {"ref": "master"},
            "author_association": "MEMBER",
        }
        if path.endswith("/pulls"):
            return github_response(json.dumps([pull]))
        if path.endswith("/pulls/7"):
            return github_response(json.dumps(pull))
        if "/contents/docs/published/docs/" in path:
            page_file = path.split("/contents/docs/published/docs/", 1)[1]
            is_published = any(page_file == f"{page_path}.mdx" for page_path in self.published_page_paths)
            return github_response("", status_code=200 if is_published else 404)
        if path.endswith("/.gitattributes"):
            return github_response("# Generated code\nposthog/schema.py linguist-generated\n")
        return github_response(GENERATED_CHUNK + SCRIPT_CHUNK + COMPONENT_CHUNK)


def github_response(body: str, status_code: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = body.encode()
    return response


def merge_subject(commit_sha: str) -> MergeSubject:
    return MergeSubject(repository="PostHog/posthog", commit_sha=commit_sha)


def finder_returning(page_urls: list[str], docs_queries: list[str]) -> Callable[[str], list[str]]:
    def find_docs_page_urls(docs_query: str) -> list[str]:
        docs_queries.append(docs_query)
        return page_urls

    return find_docs_page_urls


class FakeJudgeClient(SimpleNamespace):
    def with_options(self, **_options: object) -> "FakeJudgeClient":
        return self

    def __enter__(self) -> "FakeJudgeClient":
        return self

    def __exit__(self, *_exception: object) -> None:
        return None


def judge_with_parse(parse: Callable[..., object]) -> Anthropic:
    return cast(Anthropic, FakeJudgeClient(messages=SimpleNamespace(parse=parse)))


def judge_recording(verdict: JudgeVerdict, judge_requests: list[dict]) -> Anthropic:
    def parse(**request: object) -> object:
        judge_requests.append(request)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=verdict)

    return judge_with_parse(parse)


def judge_returning_malformed_output() -> Anthropic:
    def parse(**_request: object) -> object:
        return JudgeVerdict.model_validate({"needs_docs": "maybe"})

    return judge_with_parse(parse)


def test_merge_judged_on_non_generated_diff_carries_each_searched_docs_page_once() -> None:
    commit_sha = "a" * 40
    judge_requests: list[dict] = []
    docs_queries: list[str] = []
    verdict = JudgeVerdict(
        needs_docs=True, change_kind=DocsChangeKind.UPDATE, docs_query=DOCS_QUERY, reason="new option"
    )

    report = run_merge_check(
        merge_subject(commit_sha),
        github=FakePostHogGitHub(commit_sha),
        find_docs_page_urls=finder_returning(
            [FLAGS_PAGES[-1], *FLAGS_PAGES[:3], FLAGS_PAGES[-1], "https://posthog.com/blog/flags"], docs_queries
        ),
        anthropic_client=judge_recording(verdict, judge_requests),
    )

    judge_content = judge_requests[0]["messages"][0]["content"]
    assert (
        judge_content == f"Commit title: chore: drop legacy rollout\n\n<diff>\n{SCRIPT_CHUNK}{COMPONENT_CHUNK}\n</diff>"
    )
    assert docs_queries == [DOCS_QUERY]
    assert (report.needs_docs, report.change_kind) == (True, DocsChangeKind.UPDATE)
    assert report.page_urls == (FLAGS_PAGES[-1], *FLAGS_PAGES[:3])


def test_update_with_no_searched_docs_page_becomes_create() -> None:
    commit_sha = "c" * 40
    verdict = JudgeVerdict(
        needs_docs=True, change_kind=DocsChangeKind.UPDATE, docs_query=DOCS_QUERY, reason="new option"
    )

    report = run_merge_check(
        merge_subject(commit_sha),
        github=FakePostHogGitHub(commit_sha),
        find_docs_page_urls=finder_returning([], []),
        anthropic_client=judge_recording(verdict, []),
    )

    assert (report.needs_docs, report.change_kind, report.page_urls) == (True, DocsChangeKind.CREATE, ())


def test_a_searched_page_published_from_this_repository_skips_the_writer() -> None:
    commit_sha = "d" * 40
    verdict = JudgeVerdict(
        needs_docs=True, change_kind=DocsChangeKind.UPDATE, docs_query=DOCS_QUERY, reason="new option"
    )

    report = run_merge_check(
        merge_subject(commit_sha),
        github=FakePostHogGitHub(commit_sha, published_page_paths=(FLAGS_PATHS[1],)),
        find_docs_page_urls=finder_returning([FLAGS_PAGES[0], f"{FLAGS_PAGES[1]}/"], []),
        anthropic_client=judge_recording(verdict, []),
    )

    assert (report.needs_docs, report.reason) == (False, "docs_in_source_repo")


def test_malformed_judge_output_declines_without_searching_docs() -> None:
    commit_sha = "b" * 40
    docs_queries: list[str] = []

    report = run_merge_check(
        merge_subject(commit_sha),
        github=FakePostHogGitHub(commit_sha),
        find_docs_page_urls=finder_returning(FLAGS_PAGES, docs_queries),
        anthropic_client=judge_returning_malformed_output(),
    )

    assert (report.needs_docs, report.reason, docs_queries) == (False, "judge_declined", [])
