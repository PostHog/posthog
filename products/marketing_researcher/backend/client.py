import logging
from typing import Optional, Any
from urllib.parse import urlparse

from posthog.settings import get_from_env
from .exceptions import ExaConfigurationError, ExaAPIError, ExaValidationError

logger = logging.getLogger(__name__)

try:
    from exa_py import Exa
except ImportError:
    Exa = None
    logger.warning("exa_py not installed. Marketing Researcher functionality will be unavailable.")


class ExaClient:
    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or get_from_env("EXA_API_KEY", optional=True)
        self._client: Optional[Exa] = None

        if not self.api_key:
            raise ExaConfigurationError("EXA_API_KEY is required but not found in environment variables")

        if not Exa:
            raise ExaConfigurationError("exa_py package is not installed")

        self._initialize_client()

    def _initialize_client(self):
        try:
            self._client = Exa(api_key=self.api_key)
            logger.info("Exa client initialized successfully")
        except Exception as e:
            logger.exception(f"Failed to initialize Exa client: {e}")
            raise ExaConfigurationError(f"Failed to initialize Exa client: {e}")

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def search_and_contents(
        self,
        query: str,
        num_results: int = 10,
        search_type: str = "neural",
        use_autoprompt: bool = True,
        include_text: bool = True,
        summary_query: Optional[str] = None,
        exclude_domains: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        if not self.is_available:
            raise ExaConfigurationError("Exa client is not available")

        if not query.strip():
            raise ExaValidationError("Query cannot be empty")

        if not 1 <= num_results <= 20:
            raise ExaValidationError("num_results must be between 1 and 20")

        if search_type not in ["neural", "keyword"]:
            raise ExaValidationError("search_type must be 'neural' or 'keyword'")

        try:
            # First do the search
            search_params = {
                "query": query,
                "num_results": num_results,
                "type": search_type,
                "use_autoprompt": use_autoprompt,
            }

            if exclude_domains:
                search_params["exclude_domains"] = exclude_domains

            search_params = {k: v for k, v in search_params.items() if v is not None}

            # Get search results
            search_results = self._client.search(**search_params)

            # Then get contents if requested
            if include_text or summary_query:
                contents_params = {"ids": [result.id for result in search_results.results]}

                if include_text:
                    contents_params["text"] = True
                if summary_query:
                    contents_params["summary"] = {"query": summary_query}

                contents_results = self._client.get_contents(**contents_params)
                results = contents_results
            else:
                results = search_results

            formatted_results = []
            excluded_domains_set = set()

            # Build a comprehensive set of domains to exclude
            if exclude_domains:
                for domain in exclude_domains:
                    excluded_domains_set.add(self._extract_domain(domain).lower())

            for result in results.results:
                # Additional filtering: check if result domain matches any excluded domain
                result_domain = self._extract_domain(result.url).lower()

                # Skip if this result is from an excluded domain
                if any(
                    excluded_domain in result_domain or result_domain in excluded_domain
                    for excluded_domain in excluded_domains_set
                ):
                    logger.info(f"Filtering out same-domain result: {result.url}")
                    continue

                formatted_result = {
                    "id": getattr(result, "id", result.url),
                    "url": result.url,
                    "title": result.title,
                    "score": result.score,
                    "published_date": result.published_date,
                    "author": result.author,
                    "favicon": getattr(result, "favicon", None),
                }

                if include_text and hasattr(result, "text"):
                    formatted_result["text"] = result.text

                if summary_query and hasattr(result, "summary"):
                    formatted_result["summary"] = result.summary

                formatted_results.append(formatted_result)

            logger.info(
                f"Exa search_and_contents completed. Found {len(formatted_results)} results after filtering for query: {query}"
            )
            return formatted_results

        except Exception as e:
            logger.exception(f"Error performing search and contents: {e}")
            raise ExaAPIError(f"Search and contents failed: {e}")

    def _extract_domain(self, url: str) -> str:
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            # Remove 'www.' prefix if present
            if domain.startswith("www."):
                domain = domain[4:]

            return domain
        except Exception:
            # If parsing fails, return the original string lowercased
            return url.lower()
