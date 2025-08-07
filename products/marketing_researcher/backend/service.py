import logging
from typing import Optional, Any

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
        return self._client.search_and_contents(
            query=summary_text,
            num_results=10,
            search_type="neural",
            use_autoprompt=True,
            include_text=True,
            summary_query="Explain in one/two lines what does this company do in simple english. Don't use any difficult words.",
            exclude_domains=[website_url],
        )


marketing_researcher_service = MarketingResearcherService()
