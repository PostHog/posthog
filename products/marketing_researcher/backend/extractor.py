import logging
from typing import Any
import requests
from bs4 import BeautifulSoup
import time

logger = logging.getLogger(__name__)


class MarketingExtractor:
    def __init__(self, timeout: int = 5, delay: float = 0.1):
        self.timeout = timeout
        self.delay = delay  # Minimal delay between requests
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (compatible; PostHog-MarketingResearcher/1.0; +https://posthog.com)"}
        )

    def extract_marketing_data(self, url: str) -> dict[str, Any]:
        """
        Extract lightweight marketing data using only HEAD requests for metadata

        Returns:
            Dict containing SEO metadata and basic info
        """
        response_data = {"url": url, "seo_metadata": {}, "social_channels": {}, "error": None}

        try:
            logger.info(f"Extracting lightweight marketing intelligence from: {url}")

            # Add minimal delay
            time.sleep(self.delay)

            # First try HEAD request for just metadata
            response = self.session.head(url, timeout=self.timeout, allow_redirects=True)

            # If HEAD doesn't give us what we need, do a minimal GET for just the <head> section
            if response.status_code == 200:
                # Some servers return content-type in HEAD
                response_data["content_type"] = response.headers.get("content-type", "")
                response_data["server"] = response.headers.get("server", "")

            # Get minimal HTML just for <head> section - limit response size
            response = self.session.get(
                url,
                timeout=self.timeout,
                stream=True,
                headers={"Range": "bytes=0-8192"},  # Just first 8KB for head section
            )

            # Read only first 8KB
            content = b""
            for chunk in response.iter_content(chunk_size=1024):
                content += chunk
                if len(content) >= 8192:
                    break

            # Parse just enough to get meta tags
            soup = BeautifulSoup(content, "html.parser")

            # Extract only lightweight metadata
            response_data["seo_metadata"] = self._extract_seo_metadata(soup)
            response_data["social_channels"] = self._extract_social_from_meta(soup)

            logger.info(f"Successfully extracted lightweight data from: {url}")

        except Exception as e:
            logger.warning(f"Failed to extract marketing data from {url}: {e}")
            response_data["error"] = str(e)

        return response_data

    def _extract_seo_metadata(self, soup: BeautifulSoup) -> dict[str, str]:
        metadata = {}

        title_tag = soup.find("title")
        if title_tag:
            metadata["title"] = title_tag.get_text(strip=True)

        # Only extract the most critical meta tags
        important_meta_tags = [
            "description",
            "og:title",
            "og:description",
            "og:image",
            "twitter:title",
            "twitter:description",
            "twitter:card",
        ]

        meta_tags = soup.find_all("meta")
        for meta in meta_tags:
            name = meta.get("name") or meta.get("property")
            content = meta.get("content")

            if name and content and name.lower() in important_meta_tags:
                metadata[name.lower()] = content

        return metadata

    def _extract_social_from_meta(self, soup: BeautifulSoup) -> dict[str, str]:
        social = {}

        social_meta_tags = soup.find_all("meta")
        for meta in social_meta_tags:
            name = meta.get("name") or meta.get("property")
            content = meta.get("content")

            if name and content:
                name_lower = name.lower()
                if "twitter:site" in name_lower:
                    social["twitter"] = content
                elif "og:url" in name_lower and ("facebook.com" in content or "twitter.com" in content):
                    if "facebook.com" in content:
                        social["facebook"] = content
                    elif "twitter.com" in content:
                        social["twitter"] = content

        return social
