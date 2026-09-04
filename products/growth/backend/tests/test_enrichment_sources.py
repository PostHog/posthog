import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from requests import ConnectTimeout

from posthog.egress.firecrawl import (
    FirecrawlEgressBudgetExhausted,
    FirecrawlNotConfigured,
    FirecrawlScrapeFailed,
    FirecrawlSearchFailed,
)
from posthog.egress.firecrawl.client import FirecrawlScrape, FirecrawlSearch, FirecrawlSearchResult
from posthog.egress.limiter.policies import Priority

from products.growth.backend.enrichment.labels import MAX_INPUT_VALUE_CHARS, SourceSpec
from products.growth.backend.enrichment.sources import fetch_source, resolve_sources
from products.growth.backend.models import OrganizationEnrichment

_SOURCES_MODULE = "products.growth.backend.enrichment.sources"


def _fetch_spec(key: str = "pricing", template: str = "https://{domain}/pricing") -> SourceSpec:
    return SourceSpec(key=key, kind="fetch", template=template)


def _search_spec(key: str = "ai_news", template: str = '"{name}" AI', limit: int = 5) -> SourceSpec:
    return SourceSpec(key=key, kind="search", template=template, limit=limit)


class TestFetchSourceUnresolved(BaseTest):
    def test_an_unresolved_fetch_template_skips_the_scrape(self):
        with patch(f"{_SOURCES_MODULE}.scrape") as scrape:
            record = fetch_source(self.organization.id, _fetch_spec(), domain=None, name=None)

        assert record["error"] == "unresolved"
        assert record["url"] is None
        assert "markdown" not in record
        scrape.assert_not_called()

    def test_an_unresolved_search_template_skips_the_search(self):
        with patch(f"{_SOURCES_MODULE}.search") as search_mock:
            record = fetch_source(self.organization.id, _search_spec(), domain="acme.example", name=None)

        assert record["error"] == "unresolved"
        assert record["query"] is None
        search_mock.assert_not_called()


class TestFetchSourceFetch(BaseTest):
    def test_a_successful_scrape_yields_markdown_at_the_rendered_url(self):
        scraped = FirecrawlScrape(url="https://acme.example/pricing", markdown="Plans start at $10/mo")
        with patch(f"{_SOURCES_MODULE}.scrape", return_value=scraped) as scrape:
            record = fetch_source(self.organization.id, _fetch_spec(), domain="acme.example", name=None)

        assert record["kind"] == "fetch"
        assert record["url"] == "https://acme.example/pricing"
        assert record["markdown"] == "Plans start at $10/mo"
        assert "error" not in record
        scrape.assert_called_once_with(
            "https://acme.example/pricing",
            source="growth_ai_enrichment",
            formats=("markdown",),
            priority=Priority.BATCH,
        )

    def test_the_markdown_is_truncated_to_the_cap(self):
        scraped = FirecrawlScrape(url="https://acme.example/pricing", markdown="x" * (MAX_INPUT_VALUE_CHARS + 500))
        with patch(f"{_SOURCES_MODULE}.scrape", return_value=scraped):
            record = fetch_source(self.organization.id, _fetch_spec(), domain="acme.example", name=None)

        assert len(record["markdown"]) == MAX_INPUT_VALUE_CHARS

    @parameterized.expand(
        [
            ("not_configured", FirecrawlNotConfigured, "not_configured"),
            ("scrape_failed", FirecrawlScrapeFailed, "busy"),
            ("connect_timeout", ConnectTimeout, "busy"),
            ("budget_exhausted", FirecrawlEgressBudgetExhausted, "busy"),
        ]
    )
    def test_a_degraded_scrape_outcome_never_raises(self, _name, error, expected_error):
        with patch(f"{_SOURCES_MODULE}.scrape", side_effect=error("boom")):
            record = fetch_source(self.organization.id, _fetch_spec(), domain="acme.example", name=None)

        assert record["error"] == expected_error

    @parameterized.expand(
        [
            ("not_configured", FirecrawlNotConfigured),
            ("scrape_failed", FirecrawlScrapeFailed),
            ("connect_timeout", ConnectTimeout),
            ("budget_exhausted", FirecrawlEgressBudgetExhausted),
        ]
    )
    def test_a_transient_fetch_error_is_not_cached_so_it_retries_next_run(self, _name, error):
        with patch(f"{_SOURCES_MODULE}.scrape", side_effect=error("boom")) as scrape:
            fetch_source(self.organization.id, _fetch_spec(), domain="acme.example", name=None)
            fetch_source(self.organization.id, _fetch_spec(), domain="acme.example", name=None)

        assert scrape.call_count == 2
        assert not OrganizationEnrichment.objects.filter(organization=self.organization).exists()

    def test_a_successful_fetch_is_always_repeated_and_stores_no_markdown(self):
        scraped = FirecrawlScrape(url="https://acme.example/pricing", markdown="content")
        with patch(f"{_SOURCES_MODULE}.scrape", return_value=scraped) as scrape:
            first = fetch_source(self.organization.id, _fetch_spec(), domain="acme.example", name=None)
            second = fetch_source(self.organization.id, _fetch_spec(), domain="acme.example", name=None)

        assert scrape.call_count == 2
        assert first["markdown"] == second["markdown"] == "content"
        stored = OrganizationEnrichment.objects.get(organization=self.organization).data["sources"]["pricing"]
        assert "markdown" not in stored

    def test_a_non_2xx_status_is_cached_so_it_is_not_refetched_every_day(self):
        scraped = FirecrawlScrape(url="https://acme.example/pricing", status_code=404, markdown=None)
        with patch(f"{_SOURCES_MODULE}.scrape", return_value=scraped) as scrape:
            first = fetch_source(self.organization.id, _fetch_spec(), domain="acme.example", name=None)
            second = fetch_source(self.organization.id, _fetch_spec(), domain="acme.example", name=None)

        scrape.assert_called_once()
        assert first["error"] == "unreachable"
        assert "markdown" not in first
        assert second["error"] == "unreachable"
        assert second["source"] == "cache"

    def test_a_cached_unreachable_result_is_invalidated_by_a_changed_url(self):
        # A changed template render (a new domain, or an edited config) must not reuse a scrape of
        # a different address - url equality is the whole cache key now, not a separate domain check.
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={
                "sources": {
                    "pricing": {
                        "kind": "fetch",
                        "url": "https://old-domain.example/pricing",
                        "source": "scrape",
                        "error": "unreachable",
                        "fetched_at": timezone.now().isoformat(),
                    }
                }
            },
        )
        scraped = FirecrawlScrape(url="https://acme.example/pricing", markdown="fresh")

        with patch(f"{_SOURCES_MODULE}.scrape", return_value=scraped) as scrape:
            record = fetch_source(self.organization.id, _fetch_spec(), domain="acme.example", name=None)

        scrape.assert_called_once()
        assert record["markdown"] == "fresh"

    def test_a_fetch_older_than_the_cache_window_is_refetched(self):
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={
                "sources": {
                    "pricing": {
                        "kind": "fetch",
                        "url": "https://acme.example/pricing",
                        "source": "scrape",
                        "error": "unreachable",
                        "fetched_at": (timezone.now() - dt.timedelta(days=31)).isoformat(),
                    }
                }
            },
        )
        scraped = FirecrawlScrape(url="https://acme.example/pricing", markdown="fresh")

        with patch(f"{_SOURCES_MODULE}.scrape", return_value=scraped) as scrape:
            record = fetch_source(self.organization.id, _fetch_spec(), domain="acme.example", name=None)

        scrape.assert_called_once()
        assert record["markdown"] == "fresh"


class TestFetchSourceSearch(BaseTest):
    def test_a_successful_search_yields_results(self):
        found = FirecrawlSearch(
            query='"Acme" AI',
            results=(FirecrawlSearchResult(url="https://techcrunch.com/acme", title="Acme raises funding"),),
        )
        with patch(f"{_SOURCES_MODULE}.search", return_value=found) as search_mock:
            record = fetch_source(self.organization.id, _search_spec(), domain="acme.example", name="Acme")

        assert record["kind"] == "search"
        assert record["query"] == '"Acme" AI'
        assert record["results"] == [
            {"url": "https://techcrunch.com/acme", "title": "Acme raises funding", "description": None}
        ]
        search_mock.assert_called_once_with(
            '"Acme" AI', source="growth_ai_enrichment", limit=5, priority=Priority.BATCH
        )

    def test_zero_results_is_recorded_as_no_results_and_not_cached(self):
        found = FirecrawlSearch(query='"Acme" AI', results=())
        with patch(f"{_SOURCES_MODULE}.search", return_value=found) as search_mock:
            first = fetch_source(self.organization.id, _search_spec(), domain="acme.example", name="Acme")
            fetch_source(self.organization.id, _search_spec(), domain="acme.example", name="Acme")

        assert first["error"] == "no_results"
        assert search_mock.call_count == 2
        assert not OrganizationEnrichment.objects.filter(organization=self.organization).exists()

    @parameterized.expand(
        [
            ("not_configured", FirecrawlNotConfigured, "not_configured"),
            ("search_failed", FirecrawlSearchFailed, "busy"),
            ("connect_timeout", ConnectTimeout, "busy"),
            ("budget_exhausted", FirecrawlEgressBudgetExhausted, "busy"),
        ]
    )
    def test_a_degraded_search_outcome_never_raises(self, _name, error, expected_error):
        with patch(f"{_SOURCES_MODULE}.search", side_effect=error("boom")):
            record = fetch_source(self.organization.id, _search_spec(), domain="acme.example", name="Acme")

        assert record["error"] == expected_error

    def test_a_successful_search_is_never_cached(self):
        found = FirecrawlSearch(query='"Acme" AI', results=(FirecrawlSearchResult(url="https://x.example"),))
        with patch(f"{_SOURCES_MODULE}.search", return_value=found):
            fetch_source(self.organization.id, _search_spec(), domain="acme.example", name="Acme")

        assert not OrganizationEnrichment.objects.filter(organization=self.organization).exists()


class TestResolveSources(BaseTest):
    def test_resolves_every_declared_source_keyed_by_spec_key(self):
        scraped = FirecrawlScrape(url="https://acme.example/pricing", markdown="pricing content")
        found = FirecrawlSearch(query='"Acme" AI', results=())

        with (
            patch(f"{_SOURCES_MODULE}.scrape", return_value=scraped),
            patch(f"{_SOURCES_MODULE}.search", return_value=found),
        ):
            resolved = resolve_sources(
                self.organization.id,
                domain="acme.example",
                name="Acme",
                specs=[_fetch_spec(key="pricing"), _search_spec(key="ai_news")],
            )

        assert resolved["pricing"]["markdown"] == "pricing content"
        assert resolved["ai_news"]["error"] == "no_results"
