import logging
from typing import Optional, Any
from urllib.parse import urlparse

from .client import ExaClient
from .exceptions import ExaConfigurationError
from .extractor import MarketingExtractor

logger = logging.getLogger(__name__)


class MarketingResearcherService:
    def __init__(self):
        self._client: Optional[ExaClient] = None
        self._extractor = MarketingExtractor()
        self._initialize()

    def _initialize(self):
        try:
            self._client = ExaClient()
            logger.info("Marketing Researcher service initialized successfully")
        except ExaConfigurationError as e:
            logger.warning(f"Marketing Researcher service not available: {e}")
            self._client = None
        except Exception as e:
            logger.exception(f"Unexpected error initializing Marketing Researcher service: {e}")
            self._client = None

    @property
    def is_available(self) -> bool:
        return self._client is not None and self._client.is_available

    @property
    def client(self) -> Optional[ExaClient]:
        return self._client

    def find_competitors(self, website_url: str, summary_text: str) -> list[dict[str, Any]]:
        if not self.is_available:
            raise ExaConfigurationError("Marketing Researcher service is not available")

        # Extract domain and create comprehensive exclusion list
        excluded_domains = self._build_exclusion_list(website_url)

        # Create a competitor-focused search query
        competitor_query = self._build_competitor_query(website_url, summary_text)

        logger.info(f"Searching for competitors with query: {competitor_query}")
        logger.info(f"Excluding domains: {excluded_domains}")

        return self._client.search_and_contents(
            query=competitor_query,
            num_results=15,  # Get more results to account for filtering
            search_type="neural",
            use_autoprompt=True,
            include_text=False,  # Skip text to reduce response size
            summary_query="Describe what this company does, their main product/service, and target market in 2-3 sentences. Include key differentiators or positioning if evident.",
            exclude_domains=excluded_domains,
        )

    def _build_exclusion_list(self, website_url: str) -> list[str]:
        excluded_domains = []

        try:
            if not website_url.startswith(("http://", "https://")):
                website_url = "https://" + website_url

            parsed = urlparse(website_url)
            domain = parsed.netloc.lower()

            excluded_domains.extend(
                [
                    domain,
                    domain.replace("www.", "") if domain.startswith("www.") else f"www.{domain}",
                    parsed.netloc,
                ]
            )

            base_domain = domain.replace("www.", "") if domain.startswith("www.") else domain
            common_subdomains = ["app", "blog", "docs", "help", "support", "api", "dashboard", "admin", "us", "eu"]

            for subdomain in common_subdomains:
                excluded_domains.append(f"{subdomain}.{base_domain}")

            excluded_domains = list(dict.fromkeys(excluded_domains))

        except Exception as e:
            logger.warning(f"Error building exclusion list for {website_url}: {e}")
            excluded_domains = [website_url]

        return excluded_domains

    def _build_competitor_query(self, website_url: str, summary_text: str) -> str:
        competitor_query = f"competitors to companies like: {website_url} which aims to {summary_text}"

        return competitor_query

    def analyze_competitor_landscape(self, website_url: str, summary_text: str) -> dict[str, Any]:
        all_competitors = self.find_competitors(website_url, summary_text)

        competitor_query = self._build_competitor_query(website_url, summary_text)

        # Sort by score (highest first) and take top 5 for enrichment
        sorted_competitors = sorted(all_competitors, key=lambda x: x.get("score") or 0, reverse=True)
        top_competitors = sorted_competitors[:5]
        remaining_competitors = sorted_competitors[5:]

        logger.info(f"Enriching top {len(top_competitors)} competitors out of {len(all_competitors)} total")

        enriched_competitors = []
        for competitor in top_competitors:
            competitor_url = competitor.get("url")
            if not competitor_url:
                enriched_competitors.append(competitor)
                continue

            seo_data = self._extractor.extract_marketing_data(competitor_url)

            enriched_competitor = {**competitor, "seo_data": seo_data}
            enriched_competitors.append(enriched_competitor)

        all_competitors_final = enriched_competitors + remaining_competitors

        landscape_analysis = {
            "summary": {
                "total_competitors": len(all_competitors_final),
                "enriched_competitors": len(enriched_competitors),
                "query_processed": competitor_query,
                "target_company": {"url": website_url, "description": summary_text},
            },
            "competitors": all_competitors_final,
        }

        return landscape_analysis


marketing_researcher_service = MarketingResearcherService()
