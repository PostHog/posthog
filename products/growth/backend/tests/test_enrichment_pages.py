import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from requests import ConnectTimeout

from posthog.egress.firecrawl import FirecrawlEgressBudgetExhausted, FirecrawlNotConfigured, FirecrawlScrapeFailed
from posthog.egress.firecrawl.client import FirecrawlScrape
from posthog.egress.limiter.policies import Priority

from products.growth.backend.enrichment.pages import (
    MAX_MARKDOWN_CHARS,
    ensure_pages_fetched,
    fetch_page,
    page_types_from_input_fields,
)
from products.growth.backend.models import OrganizationEnrichment

_PAGES_MODULE = "products.growth.backend.enrichment.pages"


class TestPageTypesFromInputFields(BaseTest):
    def test_extracts_distinct_page_types(self):
        fields = ["pages.home.markdown", "pages.pricing.markdown", "name", "pages.home.url"]

        assert page_types_from_input_fields(fields) == {"home", "pricing"}

    def test_ignores_malformed_pages_paths(self):
        assert page_types_from_input_fields(["pages.home", "pages.", "pages"]) == set()

    def test_returns_empty_set_when_no_pages_fields(self):
        assert page_types_from_input_fields(["name", "funding.fundingStage"]) == set()


class TestFetchPageHome(BaseTest):
    def test_a_missing_domain_skips_the_scrape_cleanly(self):
        with patch(f"{_PAGES_MODULE}.scrape") as scrape:
            record = fetch_page(self.organization.id, None, "home")

        assert record["error"] == "no_domain"
        assert record["markdown"] is None
        scrape.assert_not_called()

    def test_a_successful_scrape_yields_markdown_at_the_domain_root(self):
        scraped = FirecrawlScrape(url="https://acme.example", markdown="# Acme\nWe build things.")
        with patch(f"{_PAGES_MODULE}.scrape", return_value=scraped) as scrape:
            record = fetch_page(self.organization.id, "acme.example", "home")

        assert record["url"] == "https://acme.example"
        assert record["markdown"] == "# Acme\nWe build things."
        assert record["domain"] == "acme.example"
        assert "error" not in record
        scrape.assert_called_once_with(
            "https://acme.example", source="growth_ai_enrichment", formats=("markdown",), priority=Priority.BATCH
        )

    def test_uses_the_batch_priority_lane(self):
        # This is a scheduled job's own traffic, not work on behalf of an interactive request, so
        # it must be the first lane the shared Firecrawl budget sheds as it fills.
        scraped = FirecrawlScrape(url="https://acme.example", markdown="content")
        with patch(f"{_PAGES_MODULE}.scrape", return_value=scraped) as scrape:
            fetch_page(self.organization.id, "acme.example", "home")

        assert scrape.call_args.kwargs["priority"] is Priority.BATCH

    def test_the_markdown_is_truncated_to_the_cap(self):
        scraped = FirecrawlScrape(url="https://acme.example", markdown="x" * (MAX_MARKDOWN_CHARS + 500))
        with patch(f"{_PAGES_MODULE}.scrape", return_value=scraped):
            record = fetch_page(self.organization.id, "acme.example", "home")

        assert len(record["markdown"]) == MAX_MARKDOWN_CHARS

    @parameterized.expand(
        [
            ("not_configured", FirecrawlNotConfigured, "not_configured"),
            ("scrape_failed", FirecrawlScrapeFailed, "unreachable"),
            ("connect_timeout", ConnectTimeout, "unreachable"),
            ("budget_exhausted", FirecrawlEgressBudgetExhausted, "busy"),
        ]
    )
    def test_a_degraded_scrape_outcome_never_raises(self, _name, error, expected_error):
        with patch(f"{_PAGES_MODULE}.scrape", side_effect=error("boom")):
            record = fetch_page(self.organization.id, "acme.example", "home")

        assert record["error"] == expected_error

    def test_a_recent_fetch_is_reused_without_calling_firecrawl_again(self):
        scraped = FirecrawlScrape(url="https://acme.example", markdown="content")
        with patch(f"{_PAGES_MODULE}.scrape", return_value=scraped) as scrape:
            first = fetch_page(self.organization.id, "acme.example", "home")
            second = fetch_page(self.organization.id, "acme.example", "home")

        scrape.assert_called_once()
        assert first == second

    def test_a_fetch_older_than_the_cache_window_is_refetched(self):
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={
                "pages": {
                    "home": {
                        "url": "https://acme.example",
                        "markdown": "stale",
                        "domain": "acme.example",
                        "fetched_at": (timezone.now() - dt.timedelta(days=31)).isoformat(),
                    }
                }
            },
        )
        scraped = FirecrawlScrape(url="https://acme.example", markdown="fresh")

        with patch(f"{_PAGES_MODULE}.scrape", return_value=scraped) as scrape:
            record = fetch_page(self.organization.id, "acme.example", "home")

        scrape.assert_called_once()
        assert record["markdown"] == "fresh"

    def test_a_cached_fetch_for_a_different_domain_is_not_reused(self):
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={
                "pages": {
                    "home": {
                        "url": "https://old-domain.example",
                        "markdown": "old",
                        "domain": "old-domain.example",
                        "fetched_at": timezone.now().isoformat(),
                    }
                }
            },
        )
        scraped = FirecrawlScrape(url="https://new-domain.example", markdown="fresh")

        with patch(f"{_PAGES_MODULE}.scrape", return_value=scraped) as scrape:
            record = fetch_page(self.organization.id, "new-domain.example", "home")

        scrape.assert_called_once()
        assert record["markdown"] == "fresh"

    def test_an_unreachable_page_is_cached_so_it_is_not_refetched_every_day(self):
        with patch(f"{_PAGES_MODULE}.scrape", side_effect=FirecrawlScrapeFailed("boom")) as scrape:
            fetch_page(self.organization.id, "acme.example", "home")
            record = fetch_page(self.organization.id, "acme.example", "home")

        scrape.assert_called_once()
        assert record["error"] == "unreachable"

    def test_a_budget_exhausted_outcome_is_not_cached_so_it_retries_next_run(self):
        with patch(f"{_PAGES_MODULE}.scrape", side_effect=FirecrawlEgressBudgetExhausted("boom")) as scrape:
            fetch_page(self.organization.id, "acme.example", "home")
            fetch_page(self.organization.id, "acme.example", "home")

        assert scrape.call_count == 2


class TestFetchPagePricing(BaseTest):
    def test_scrapes_the_conventional_pricing_path_directly(self):
        scraped = FirecrawlScrape(url="https://acme.example/pricing", markdown="Plans start at $10/mo")
        with patch(f"{_PAGES_MODULE}.scrape", return_value=scraped) as scrape:
            record = fetch_page(self.organization.id, "acme.example", "pricing")

        scrape.assert_called_once_with(
            "https://acme.example/pricing",
            source="growth_ai_enrichment",
            formats=("markdown",),
            priority=Priority.BATCH,
        )
        assert record["url"] == "https://acme.example/pricing"
        assert record["markdown"] == "Plans start at $10/mo"

    def test_a_missing_pricing_page_is_cached_as_unreachable(self):
        with patch(f"{_PAGES_MODULE}.scrape", side_effect=FirecrawlScrapeFailed("404")) as scrape:
            first = fetch_page(self.organization.id, "acme.example", "pricing")
            second = fetch_page(self.organization.id, "acme.example", "pricing")

        scrape.assert_called_once()
        assert first["error"] == "unreachable"
        assert first["markdown"] is None
        assert second == first


class TestFetchPageUnsupportedType(BaseTest):
    def test_an_unresolvable_page_type_degrades_without_calling_firecrawl(self):
        with patch(f"{_PAGES_MODULE}.scrape") as scrape:
            record = fetch_page(self.organization.id, "acme.example", "careers")

        assert record["error"] == "unsupported_type"
        scrape.assert_not_called()

    def test_an_unsupported_type_is_not_cached(self):
        with patch(f"{_PAGES_MODULE}.scrape"):
            fetch_page(self.organization.id, "acme.example", "careers")

        assert not OrganizationEnrichment.objects.filter(organization=self.organization).exists()


class TestEnsurePagesFetched(BaseTest):
    def test_fetches_every_named_type_and_keys_the_result_by_type(self):
        # side_effect keyed by URL, not list position: {"home", "pricing"} is a set, so
        # ensure_pages_fetched's iteration order over page_types is not guaranteed.
        def _scrape(url, **kwargs):
            markdown = "home content" if url == "https://acme.example" else "pricing content"
            return FirecrawlScrape(url=url, markdown=markdown)

        with patch(f"{_PAGES_MODULE}.scrape", side_effect=_scrape):
            pages = ensure_pages_fetched(self.organization.id, "acme.example", {"home", "pricing"})

        assert pages["home"]["markdown"] == "home content"
        assert pages["pricing"]["markdown"] == "pricing content"
