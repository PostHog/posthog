import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest

import httpx
import requests
from anthropic import Anthropic

from products.knowledge_writer.backend.facade.enums import DocsChangeKind
from products.knowledge_writer.merge_check.check import run_merge_check
from products.knowledge_writer.merge_check.judge import JudgeVerdict

COMPONENT_PATH = "products/feature_flags/frontend/FlagBanner.tsx"
COMPONENT_CHUNK = f"diff --git a/{COMPONENT_PATH} b/{COMPONENT_PATH}\n-old\n+new\n"
SCRIPT_CHUNK = "diff --git a/bin/start b/bin/start\n-old\n+new\n"
GENERATED_CHUNK = "diff --git a/posthog/schema.py b/posthog/schema.py\n-old\n+new\n"
FLAGS_PATHS = [f"feature-flags/page-{number}" for number in range(200)]
FLAGS_PAGES = [f"https://posthog.com/docs/{path}" for path in FLAGS_PATHS]


class FakePostHogGitHub:
    def __init__(
        self,
        commit_sha: str,
        published_page_paths: tuple[str, ...] = (),
        *,
        is_commit_indexed: bool = True,
        compare_status: str = "behind",
    ) -> None:
        self.commit_sha = commit_sha
        self.published_page_paths = published_page_paths
        self.is_commit_indexed = is_commit_indexed
        self.compare_status = compare_status

    def merged_pull_request(self) -> dict[str, object]:
        return {
            "number": 7,
            "title": "chore: drop legacy rollout",
            "html_url": "https://github.com/PostHog/posthog/pull/7",
            "merge_commit_sha": self.commit_sha,
            "merged_at": "2026-10-27T00:00:00Z",
            "base": {"ref": "stack/parent-branch"},
            "author_association": "MEMBER",
        }

    def api_request(self, method: str, path: str, **_options: object) -> requests.Response:
        if path.endswith(f"/commits/{self.commit_sha}/pulls"):
            pulls = [self.merged_pull_request()] if self.is_commit_indexed else []
            return github_response(json.dumps(pulls))
        if path.endswith("/pulls/7"):
            return github_response(json.dumps(self.merged_pull_request()))
        if "/compare/" in path:
            return github_response(json.dumps({"status": self.compare_status}))
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


def fake_sitemap() -> httpx.Client:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="".join(f"<loc>{url}</loc>" for url in FLAGS_PAGES))

    return httpx.Client(transport=httpx.MockTransport(respond))


def judge_with_parse(parse: Callable[..., object]) -> Anthropic:
    client = SimpleNamespace(messages=SimpleNamespace(parse=parse))
    client.with_options = lambda **_options: client
    return cast(Anthropic, client)


def judge_recording(verdict: JudgeVerdict, judge_requests: list[dict]) -> Anthropic:
    def parse(**request: object) -> object:
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

    report = run_merge_check(
        commit_sha,
        pull_request_number=7,
        github=FakePostHogGitHub(commit_sha),
        http=fake_sitemap(),
        anthropic_client=judge_recording(verdict, judge_requests),
    )

    judge_content = judge_requests[0]["messages"][0]["content"]
    assert "Docs pages:\n" + "\n".join(FLAGS_PATHS) + "\n\n<diff>" in judge_content
    assert judge_content.endswith(f"<diff>\n{SCRIPT_CHUNK}{COMPONENT_CHUNK}\n</diff>")
    assert (report.needs_docs, report.change_kind) == (True, DocsChangeKind.UPDATE)
    assert report.page_urls == (FLAGS_PAGES[-1], *FLAGS_PAGES[:3])


def test_update_naming_no_sitemap_page_becomes_create() -> None:
    commit_sha = "c" * 40
    verdict = JudgeVerdict(
        needs_docs=True, change_kind=DocsChangeKind.UPDATE, page_urls=["product-analytics/alerts"], reason="new option"
    )

    report = run_merge_check(
        commit_sha,
        pull_request_number=7,
        github=FakePostHogGitHub(commit_sha),
        http=fake_sitemap(),
        anthropic_client=judge_recording(verdict, []),
    )

    assert (report.needs_docs, report.change_kind, report.page_urls) == (True, DocsChangeKind.CREATE, ())


@pytest.mark.parametrize("published_page_path", [FLAGS_PATHS[1], "surveys/not-in-the-sitemap-yet"])
def test_a_page_published_from_this_repository_skips_the_writer(published_page_path: str) -> None:
    commit_sha = "d" * 40
    verdict = JudgeVerdict(
        needs_docs=True,
        change_kind=DocsChangeKind.UPDATE,
        page_urls=[FLAGS_PATHS[0], f"{published_page_path}/"],
        reason="new option",
    )

    report = run_merge_check(
        commit_sha,
        pull_request_number=7,
        github=FakePostHogGitHub(commit_sha, published_page_paths=(published_page_path,)),
        http=fake_sitemap(),
        anthropic_client=judge_recording(verdict, []),
    )

    assert (report.needs_docs, report.reason) == (False, "docs_in_source_repo")


def test_malformed_judge_output_declines_instead_of_raising() -> None:
    commit_sha = "b" * 40

    report = run_merge_check(
        commit_sha,
        pull_request_number=7,
        github=FakePostHogGitHub(commit_sha),
        http=fake_sitemap(),
        anthropic_client=judge_returning_malformed_output(),
    )

    assert (report.needs_docs, report.reason) == (False, "judge_declined")


@pytest.mark.parametrize(
    "pull_request_number, is_commit_indexed, compare_status, expected_reason",
    [
        pytest.param(7, False, "behind", "no docs needed", id="webhook_merge_before_github_indexes_the_commit"),
        pytest.param(None, True, "identical", "no docs needed", id="replay_looks_the_pull_request_up_by_commit"),
        pytest.param(None, False, "behind", "no_pull_request", id="commit_without_a_pull_request"),
        pytest.param(7, True, "diverged", "not_on_mainline", id="merged_into_a_branch_that_never_reached_master"),
    ],
)
def test_a_merged_pull_request_with_any_base_is_judged_once_its_commit_is_on_master(
    pull_request_number: int | None, is_commit_indexed: bool, compare_status: str, expected_reason: str
) -> None:
    commit_sha = "e" * 40
    judge_requests: list[dict] = []
    verdict = JudgeVerdict(needs_docs=False, change_kind=None, page_urls=[], reason="no docs needed")

    report = run_merge_check(
        commit_sha,
        pull_request_number=pull_request_number,
        github=FakePostHogGitHub(commit_sha, is_commit_indexed=is_commit_indexed, compare_status=compare_status),
        http=fake_sitemap(),
        anthropic_client=judge_recording(verdict, judge_requests),
    )

    assert (report.needs_docs, report.reason) == (False, expected_reason)
    assert bool(judge_requests) == (expected_reason == verdict.reason)
