import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx
from anthropic import Anthropic

from products.knowledge_writer.backend.facade.enums import DocsChangeKind
from products.knowledge_writer.merge_check.check import Checkouts, run_merge_check
from products.knowledge_writer.merge_check.judge import JudgeVerdict

COMPONENT_PATH = "products/feature_flags/frontend/FlagBanner.tsx"
REMOVED_COPY = "Turn on legacy flag rollout"
FLAGS_PAGES = [f"https://posthog.com/docs/feature-flags/page-{number}" for number in range(5)]


def git(checkout: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), *arguments], capture_output=True, text=True, check=True
    ).stdout.strip()


def commit_component(checkout: Path, copy: str) -> str:
    component = checkout / COMPONENT_PATH
    component.parent.mkdir(parents=True, exist_ok=True)
    component.write_text(f"export const FlagBanner = () => <div>{copy}</div>\n")
    git(checkout, "add", "-A")
    git(checkout, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qm", copy)
    return git(checkout, "rev-parse", "HEAD")


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


def judge_returning(verdict: JudgeVerdict) -> Anthropic:
    parse = lambda **_request: SimpleNamespace(stop_reason="end_turn", parsed_output=verdict)
    return cast(Anthropic, SimpleNamespace(messages=SimpleNamespace(parse=parse)))


def test_removed_product_string_still_quoted_in_docs_yields_remove_report(tmp_path: Path) -> None:
    posthog_checkout, docs_checkout = tmp_path / "posthog", tmp_path / "posthog.com"
    posthog_checkout.mkdir()
    git(posthog_checkout, "init", "-q")
    commit_component(posthog_checkout, REMOVED_COPY)
    commit_sha = commit_component(posthog_checkout, "Rollouts are automatic")
    quoting_page = docs_checkout / "contents/docs/feature-flags/rollouts.mdx"
    quoting_page.parent.mkdir(parents=True)
    quoting_page.write_text(f"Click **{REMOVED_COPY}** to start.\n")

    report = run_merge_check(
        commit_sha,
        github=fake_github_and_sitemap(commit_sha),
        http=fake_github_and_sitemap(commit_sha),
        anthropic_client=judge_returning(JudgeVerdict(needs_docs=False, change_kind=None, page_urls=[], reason="")),
        checkouts=Checkouts(posthog=posthog_checkout, docs=docs_checkout),
    )

    assert (report.needs_docs, report.change_kind) == (True, DocsChangeKind.REMOVE)
    assert report.page_urls == ("https://posthog.com/docs/feature-flags/rollouts",)
    assert REMOVED_COPY in report.evidence


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
        checkouts=None,
    )

    assert (report.needs_docs, report.change_kind) == (True, DocsChangeKind.UPDATE)
    assert report.page_urls == tuple(FLAGS_PAGES[:3])
