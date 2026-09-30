from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

import httpx
from anthropic import APIConnectionError
from parameterized import parameterized

from posthog.egress.firecrawl.client import FirecrawlSearch, FirecrawlSearchFailed, FirecrawlSearchResult

from products.web_analytics.backend.content_autopilot.edits import PageEdit, apply_edits
from products.web_analytics.backend.content_autopilot.llm import ContentAutopilotLLMError, call_json
from products.web_analytics.backend.content_autopilot.research import (
    ResearchBundle,
    SourceDocument,
    fetch_site_page,
    search_site_pages,
)
from products.web_analytics.backend.content_autopilot.validation import (
    check_competitor_overlap,
    check_internal_links,
    check_ledger_sources,
    check_structure,
)
from products.web_analytics.backend.public_url_fetch import FetchedPublicUrl

SITE_PAGES = [
    "https://example.com/docs/session-replay",
    "https://example.com/docs/session-replay/privacy-controls",
    "https://example.com/pricing",
]


REPLAY_DOC = "# Session replay\n\nSession replay records what users do and plays it back with console logs."


COMPETITOR_SENTENCE = "rival replays every session with pixel perfect fidelity across all browsers"


GOOD_MARKDOWN = (
    "# How session replay works\n\n"
    + "Session replay records what users do and plays it back so you can see where they struggle. " * 3
    + "\n\n## What does session replay capture?\n\n"
    + "It captures clicks, scrolls, and console logs alongside each recording for debugging. " * 20
    + "\n\nRead more in the [session replay docs](/docs/session-replay).\n\n"
    + "## Frequently asked questions\n\n### Is it private?\n\nYes, see [privacy controls](/docs/session-replay/privacy-controls).\n"
)


class _FakeStream:
    def __init__(self, events: Iterator[SimpleNamespace]) -> None:
        self._events = events

    def __iter__(self) -> Iterator[SimpleNamespace]:
        return self._events

    def close(self) -> None:
        pass


class _DroppingStreamClient:
    def __init__(self) -> None:
        self.calls = 0
        self.messages = SimpleNamespace(create=self._create)

    def with_options(self, **kwargs: Any) -> "_DroppingStreamClient":
        return self

    def _create(self, **kwargs: Any) -> _FakeStream:
        self.calls += 1
        dropped = self.calls == 1

        def events() -> Iterator[SimpleNamespace]:
            yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text='{"ok": '))
            if dropped:
                raise httpx.RemoteProtocolError("peer closed connection")
            yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="true}"))
            yield SimpleNamespace(type="message_delta", delta=SimpleNamespace(stop_reason="end_turn"))

        return _FakeStream(events())


class TestCallJson(SimpleTestCase):
    def test_retries_a_stream_that_drops_mid_response(self) -> None:
        client = _DroppingStreamClient()

        with patch("products.web_analytics.backend.content_autopilot.llm.time.sleep"):
            result = call_json(client, system="s", user="u", schema={}, max_tokens=10, team_id=1)  # type: ignore[arg-type]

        assert result == {"ok": True}
        assert client.calls == 2

    def test_stops_retrying_at_the_callers_deadline(self) -> None:
        clock = SimpleNamespace(now=0.0)
        calls: list[float] = []

        def create(**kwargs: Any) -> _FakeStream:
            calls.append(kwargs["timeout"])
            raise APIConnectionError(request=httpx.Request("POST", "https://gateway.example.com"))

        def sleep(seconds: float) -> None:
            clock.now += seconds

        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        client.with_options = lambda **kwargs: client
        fake_time = SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep)

        with patch("products.web_analytics.backend.content_autopilot.llm.time", fake_time):
            with self.assertRaises(ContentAutopilotLLMError):
                call_json(client, system="s", user="u", schema={}, max_tokens=10, team_id=1, timeout_seconds=5.0)  # type: ignore[arg-type]

        assert calls == [5.0, 3.0]


EDITABLE_PAGE = """# Session replay

Old intro.

  ## What does it capture?

Clicks.

```bash
# install
```python
# not a heading
```

### Console logs

Logs too.

## Pricing

```Free``` forever.

```text
a


b
```

## Frequently asked questions

### Is it free?

Yes.
"""


class TestApplyEdits(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "replacing_a_section_drops_its_subsections",
                PageEdit(
                    action="replace_section",
                    heading="What does it capture?",
                    markdown="## What does it capture?\n\nEverything.",
                ),
                ["Everything.", "## Pricing"],
                ["Clicks.", "Console logs", "# install", "# not a heading"],
                (),
            ),
            (
                "inserting_after_a_section_skips_its_subsections",
                PageEdit(
                    action="insert_after_section", heading="What does it capture?", markdown="## Is it private?\n\nYes."
                ),
                ["Logs too.", "## Is it private?", "## Pricing"],
                [],
                (),
            ),
            (
                "replacing_the_intro_keeps_the_title",
                PageEdit(action="replace_intro", heading="", markdown="New answer."),
                ["# Session replay", "New answer.", "  ## What does it capture?"],
                ["Old intro."],
                (),
            ),
            (
                "appending_lands_before_the_faq",
                PageEdit(action="append", heading="", markdown="## How do I start?\n\nInstall."),
                ["## Pricing", "## How do I start?", "## Frequently asked questions"],
                [],
                (),
            ),
            (
                "an_unknown_heading_is_appended_and_reported",
                PageEdit(action="replace_section", heading="Nope", markdown="## Setup\n\nSteps."),
                ["b\n```", "## Setup", "## Frequently asked questions"],
                [],
                ("Nope",),
            ),
        ]
    )
    def test_places_the_edit(
        self, _name: str, edit: PageEdit, ordered: list[str], absent: list[str], unplaced: tuple[str, ...]
    ) -> None:
        applied = apply_edits(EDITABLE_PAGE, [edit])

        positions = [applied.markdown.index(fragment) for fragment in ordered]
        assert positions == sorted(positions)
        assert all(fragment not in applied.markdown for fragment in absent)
        assert applied.unplaced == unplaced
        assert "a\n\n\nb" in applied.markdown


class TestSearchSitePages(SimpleTestCase):
    def test_maps_results_onto_sitemap_pages_and_drops_other_sites(self) -> None:
        results = FirecrawlSearch(
            query="q",
            results=(
                FirecrawlSearchResult(url="https://www.example.com/docs/session-replay/"),
                FirecrawlSearchResult(url="https://rival.example/replay"),
                FirecrawlSearchResult(url="https://example.com/compare/best-replay-tools"),
            ),
        )
        with patch("products.web_analytics.backend.content_autopilot.research.search", return_value=results) as search:
            pages = search_site_pages("best replay tool", site_origin="https://example.com", site_urls=SITE_PAGES)

        assert search.call_args.args[0] == "site:example.com best replay tool"
        assert pages == ["https://example.com/docs/session-replay", "https://example.com/compare/best-replay-tools"]

    def test_finds_nothing_when_search_fails(self) -> None:
        with patch(
            "products.web_analytics.backend.content_autopilot.research.search",
            side_effect=FirecrawlSearchFailed("unavailable"),
        ):
            assert search_site_pages("best replay tool", site_origin="https://example.com", site_urls=SITE_PAGES) == []


class TestFetchSitePage(SimpleTestCase):
    @parameterized.expand(
        [
            ("full_twin", REPLAY_DOC, REPLAY_DOC, None),
            (
                "twin_with_a_notice_for_agents",
                "> AI agents: this is one page from the docs.\n\n" + REPLAY_DOC,
                REPLAY_DOC,
                "AI agents",
            ),
            (
                "stub_twin_linking_to_its_page",
                "# Session replay\n\nFull page: https://example.com/docs/session-replay",
                "Session replay records every click, scroll and console error in the browser.",
                None,
            ),
        ]
    )
    def test_prefers_the_richer_page_body(self, _name: str, twin: str, expected_text: str, absent: str | None) -> None:
        html = "<html><title>Session replay</title><body><p>Session replay records every click, scroll and console error in the browser.</p></body></html>"

        def fetch(url: str, **kwargs: Any) -> FetchedPublicUrl:
            if url.endswith(".md"):
                return FetchedPublicUrl(status_code=200, headers={"content-type": "text/markdown"}, body=twin.encode())
            return FetchedPublicUrl(status_code=200, headers={"content-type": "text/html"}, body=html.encode())

        with patch("products.web_analytics.backend.content_autopilot.research.fetch_public_url", side_effect=fetch):
            document = fetch_site_page("https://example.com/docs/session-replay")

        assert document is not None
        assert expected_text in document.text
        assert absent is None or absent not in document.text


class TestValidationChecks(SimpleTestCase):
    @parameterized.expand(
        [
            ("relative_known", "[a](/pricing)", True),
            ("markdown_twin_of_known", "[a](/pricing.md)", True),
            ("absolute_same_site_known", "[a](https://www.example.com/pricing/)", True),
            ("external_is_ignored", "[a](https://rival.example/x)", True),
            ("protocol_relative_external_is_ignored", "[a](//rival.example/x)", True),
            ("protocol_relative_same_site_unknown", "[a](//example.com/nope)", False),
            ("relative_unknown", "[a](/nope)", False),
        ]
    )
    def test_internal_links(self, _name: str, markdown: str, passed: bool) -> None:
        check = check_internal_links(markdown, site_origin="https://example.com", site_urls=SITE_PAGES)
        assert check.passed is passed

    @parameterized.expand(
        [
            ("researched_competitor_page", "competitor", "https://rival.example/replay", True),
            ("unresearched_competitor_page", "competitor", "https://rival.example/pricing", False),
            ("researched_site_page", "site", "https://www.example.com/pricing/", True),
            ("relative_site_page", "site", "/pricing", True),
            ("same_path_on_another_site", "site", "https://rival.example/pricing", False),
        ]
    )
    def test_claims_must_cite_a_researched_page(self, _name: str, ledger: str, source_url: str, passed: bool) -> None:
        research = ResearchBundle(
            prompt="p",
            target_url="",
            documents=(
                SourceDocument(url="https://example.com/pricing", title="", text="Free tier.", origin="site"),
                SourceDocument(
                    url="https://rival.example/replay", title="", text="Rival costs $10.", origin="competitor"
                ),
            ),
            link_candidates=(),
            skipped=(),
        )
        claim = {"claim": "Costs $10.", "source_url": source_url, "quote": "Costs $10."}

        if ledger == "site":
            check = check_ledger_sources([claim], research)
        else:
            check = check_ledger_sources([], research, competitor_ledger=[claim])

        assert check.passed is passed

    @parameterized.expand(
        [
            ("problem_already_on_the_page", "# A\n\n# B\n\n" + GOOD_MARKDOWN.split("\n", 1)[1], True),
            ("problem_added_by_the_edit", "# A\n\n" + "word " * 300, False),
        ]
    )
    def test_structure_of_an_improvement_ignores_what_the_page_already_had(
        self, _name: str, improved: str, passed: bool
    ) -> None:
        original = "# A\n\n# B\n\n## Section\n\n" + "word " * 300

        assert check_structure(improved, baseline=original).passed is passed

    def test_competitor_overlap_detects_copied_passages_regardless_of_case_and_spacing(self) -> None:
        research = ResearchBundle(
            prompt="p",
            target_url="",
            documents=(
                SourceDocument(url="https://rival.example", title="", text=COMPETITOR_SENTENCE, origin="competitor"),
            ),
            link_candidates=(),
            skipped=(),
        )
        copied = "Intro. " + COMPETITOR_SENTENCE.upper().replace(" ", "  ") + " outro."
        assert check_competitor_overlap(copied, research).passed is False
        assert check_competitor_overlap("An original sentence about replays and browsers.", research).passed is True
