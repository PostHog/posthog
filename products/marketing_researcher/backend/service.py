import logging
from typing import Optional, Any
from urllib.parse import urlparse

from .client import ExaClient
from .exceptions import ExaConfigurationError

logger = logging.getLogger(__name__)


class MarketingResearcherService:
    def __init__(self):
        self._client: Optional[ExaClient] = None
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
        competitor_query = self._build_competitor_query(summary_text)

        logger.info(f"Searching for competitors with query: {competitor_query}")
        logger.info(f"Excluding domains: {excluded_domains}")

        return self._client.search_and_contents(
            query=competitor_query,
            num_results=15,  # Get more results to account for filtering
            search_type="neural",
            use_autoprompt=True,
            include_text=False,  # Skip text to reduce response size
            summary_query="Explain in one/two lines what does this company do in simple english. Don't use any difficult words.",
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

    def _build_competitor_query(self, summary_text: str) -> str:
        competitor_query = f"competitors to companies like: {summary_text}"

        return competitor_query


marketing_researcher_service = MarketingResearcherService()
