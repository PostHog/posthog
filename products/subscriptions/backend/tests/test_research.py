from __future__ import annotations

from posthog.egress.firecrawl import FirecrawlNotConfigured

from products.subscriptions.backend.facade.research import run_public_research


def test_run_public_research_returns_only_three_bounded_citations(monkeypatch) -> None:
    class SearchResult:
        def __init__(self, url: str) -> None:
            self.url = url
            self.title = "Example"
            self.description = None

    class Scrape:
        def __init__(self, url: str) -> None:
            self.url = url
            self.title = "Example"
            self.markdown = "Useful evidence."

    monkeypatch.setattr(
        "products.subscriptions.backend.facade.research.search_public_web",
        lambda *_, **__: tuple(SearchResult(f"https://example.com/{index}") for index in range(4)),
    )
    monkeypatch.setattr(
        "products.subscriptions.backend.facade.research.scrape_public_url",
        lambda url, **_: Scrape(url),
    )

    result = run_public_research("Why did checkout conversion fall?")

    assert result.degradation is None
    assert len(result.citations) == 3
    assert [citation.url for citation in result.citations] == [
        "https://example.com/0",
        "https://example.com/1",
        "https://example.com/2",
    ]


def test_run_public_research_degrades_when_firecrawl_is_not_configured(monkeypatch) -> None:
    def unavailable(*_, **__):
        raise FirecrawlNotConfigured("missing")

    monkeypatch.setattr("products.subscriptions.backend.facade.research.search_public_web", unavailable)

    result = run_public_research("Why did checkout conversion fall?")

    assert result.citations == ()
    assert result.degradation == "not_configured"
