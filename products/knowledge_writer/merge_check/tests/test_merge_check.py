from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import httpx
from anthropic import Anthropic

from products.knowledge_writer.backend.facade.enums import DocsChangeKind
from products.knowledge_writer.merge_check.check import run_merge_check
from products.knowledge_writer.merge_check.judge import JudgeVerdict

COMPONENT_PATH = "products/feature_flags/frontend/FlagBanner.tsx"
FLAGS_PAGES = [f"https://posthog.com/docs/feature-flags/page-{number}" for number in range(5)]


def fake_github_and_sitemap(commit_sha: str) -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls"):
            pulls = [
                {
                    "number": 7,
                    "title": "chore: drop legacy rollout",
                    "html_url": "https://github.com/PostHog/posthog/pull/7",
                    "merge_commit_sha": commit_sha,
                    "author_association": "MEMBER",
                }
            ]
            return httpx.Response(200, json=pulls)
        if request.url.host == "posthog.com":
            return httpx.Response(200, text="".join(f"<loc>{url}</loc>" for url in FLAGS_PAGES))
        diff = f"diff --git a/{COMPONENT_PATH} b/{COMPONENT_PATH}\n-old\n+new\n"
        return httpx.Response(200, text=diff)

    return httpx.Client(transport=httpx.MockTransport(respond), base_url="https://api.github.com")


def judge_with_parse(parse: Callable[..., object]) -> Anthropic:
    client = SimpleNamespace(messages=SimpleNamespace(parse=parse))
    client.with_options = lambda **_options: client
    return cast(Anthropic, client)


def judge_returning(verdict: JudgeVerdict) -> Anthropic:
    return judge_with_parse(lambda **_request: SimpleNamespace(stop_reason="end_turn", parsed_output=verdict))


def judge_returning_malformed_output() -> Anthropic:
    def parse(**_request: object) -> object:
        return JudgeVerdict.model_validate({"needs_docs": "maybe"})

    return judge_with_parse(parse)


def test_mapped_merge_flagged_by_judge_yields_kind_and_at_most_three_listed_pages() -> None:
    commit_sha = "a" * 40
    verdict = JudgeVerdict(
        needs_docs=True,
        change_kind=DocsChangeKind.UPDATE,
        page_urls=[*FLAGS_PAGES, "https://example.com/not-listed"],
        reason="new option",
    )

    report = run_merge_check(
        commit_sha,
        github=fake_github_and_sitemap(commit_sha),
        http=fake_github_and_sitemap(commit_sha),
        anthropic_client=judge_returning(verdict),
    )

    assert (report.needs_docs, report.change_kind) == (True, DocsChangeKind.UPDATE)
    assert report.page_urls == tuple(FLAGS_PAGES[:3])


def test_malformed_judge_output_declines_instead_of_raising() -> None:
    commit_sha = "b" * 40

    report = run_merge_check(
        commit_sha,
        github=fake_github_and_sitemap(commit_sha),
        http=fake_github_and_sitemap(commit_sha),
        anthropic_client=judge_returning_malformed_output(),
    )

    assert (report.needs_docs, report.reason) == (False, "judge_declined")
