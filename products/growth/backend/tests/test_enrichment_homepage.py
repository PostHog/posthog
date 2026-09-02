import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from requests import ConnectTimeout

from posthog.egress.firecrawl import FirecrawlEgressBudgetExhausted, FirecrawlNotConfigured, FirecrawlScrapeFailed
from posthog.egress.firecrawl.client import FirecrawlScrape

from products.growth.backend.enrichment.homepage import MAX_EXCERPT_CHARS, homepage_input_fields
from products.growth.backend.models import OrganizationEnrichment

_HOMEPAGE_MODULE = "products.growth.backend.enrichment.homepage"


class TestHomepageInputFields(BaseTest):
    def test_a_missing_domain_skips_the_scrape_cleanly(self):
        with patch(f"{_HOMEPAGE_MODULE}.scrape") as scrape:
            fields = homepage_input_fields(self.organization.id, None)

        assert fields == {"homepage_fetch_outcome": "no_domain"}
        scrape.assert_not_called()

    def test_a_successful_scrape_yields_summary_and_excerpt(self):
        scraped = FirecrawlScrape(
            url="https://acme.example", markdown="# Acme\nWe build things.", summary="Acme builds things."
        )
        with patch(f"{_HOMEPAGE_MODULE}.scrape", return_value=scraped) as scrape:
            fields = homepage_input_fields(self.organization.id, "acme.example")

        assert fields == {
            "homepage_fetch_outcome": "scraped",
            "homepage_summary": "Acme builds things.",
            "homepage_excerpt": "# Acme\nWe build things.",
        }
        scrape.assert_called_once_with(
            "https://acme.example",
            source="growth_ai_enrichment",
            formats=("markdown", "summary"),
            timeout=(5.0, 45.0),
        )

    def test_the_excerpt_is_truncated_to_the_cap(self):
        scraped = FirecrawlScrape(url="https://acme.example", markdown="x" * (MAX_EXCERPT_CHARS + 500), summary="short")
        with patch(f"{_HOMEPAGE_MODULE}.scrape", return_value=scraped):
            fields = homepage_input_fields(self.organization.id, "acme.example")

        assert len(fields["homepage_excerpt"]) == MAX_EXCERPT_CHARS

    @parameterized.expand(
        [
            ("not_configured", FirecrawlNotConfigured, "not_configured"),
            ("scrape_failed", FirecrawlScrapeFailed, "unreachable"),
            ("connect_timeout", ConnectTimeout, "unreachable"),
            ("budget_exhausted", FirecrawlEgressBudgetExhausted, "busy"),
        ]
    )
    def test_a_degraded_scrape_outcome_never_raises(self, _name, error, expected_outcome):
        with patch(f"{_HOMEPAGE_MODULE}.scrape", side_effect=error("boom")):
            fields = homepage_input_fields(self.organization.id, "acme.example")

        assert fields == {"homepage_fetch_outcome": expected_outcome}

    def test_a_recent_scrape_is_reused_without_calling_firecrawl_again(self):
        scraped = FirecrawlScrape(url="https://acme.example", markdown="content", summary="summary")
        with patch(f"{_HOMEPAGE_MODULE}.scrape", return_value=scraped) as scrape:
            first = homepage_input_fields(self.organization.id, "acme.example")
            second = homepage_input_fields(self.organization.id, "acme.example")

        scrape.assert_called_once()
        assert first == second

    def test_a_scrape_older_than_the_cache_window_is_refetched(self):
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={
                "homepage": {
                    "domain": "acme.example",
                    "fetched_at": (timezone.now() - dt.timedelta(days=31)).isoformat(),
                    "outcome": "scraped",
                    "summary": "stale",
                    "excerpt": "stale",
                }
            },
        )
        scraped = FirecrawlScrape(url="https://acme.example", markdown="fresh", summary="fresh summary")

        with patch(f"{_HOMEPAGE_MODULE}.scrape", return_value=scraped) as scrape:
            fields = homepage_input_fields(self.organization.id, "acme.example")

        scrape.assert_called_once()
        assert fields["homepage_summary"] == "fresh summary"

    def test_a_scrape_within_the_cache_window_is_not_refetched(self):
        OrganizationEnrichment.objects.create(
            organization=self.organization,
            data={
                "homepage": {
                    "domain": "acme.example",
                    "fetched_at": (timezone.now() - dt.timedelta(days=29)).isoformat(),
                    "outcome": "scraped",
                    "summary": "cached summary",
                    "excerpt": "cached excerpt",
                }
            },
        )

        with patch(f"{_HOMEPAGE_MODULE}.scrape") as scrape:
            fields = homepage_input_fields(self.organization.id, "acme.example")

        scrape.assert_not_called()
        assert fields["homepage_summary"] == "cached summary"
