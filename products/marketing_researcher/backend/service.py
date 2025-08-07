import logging
import json
from typing import Optional, Any
from urllib.parse import urlparse

import openai
from .client import ExaClient
from .exceptions import ExaConfigurationError
from .extractor import MarketingExtractor
from .prompts import MARKETING_RECOMMENDATIONS_PROMPT

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

    def find_competitors_only(self, website_url: str, summary_text: str) -> dict[str, Any]:
        all_competitors = self.find_competitors(website_url, summary_text)
        competitor_query = self._build_competitor_query(website_url, summary_text)

        sorted_competitors = sorted(all_competitors, key=lambda x: x.get("score") or 0, reverse=True)

        return {
            "competitors": sorted_competitors,
            "query_processed": competitor_query,
            "target_company": {"url": website_url, "description": summary_text},
            "total_competitors": len(sorted_competitors),
        }

    def enrich_competitors(self, competitors: list[dict[str, Any]], max_enrich: int = 5) -> list[dict[str, Any]]:
        top_competitors = competitors[:max_enrich]
        remaining_competitors = competitors[max_enrich:]

        logger.info(f"Enriching top {len(top_competitors)} competitors out of {len(competitors)} total")

        enriched_competitors = []
        for competitor in top_competitors:
            competitor_url = competitor.get("url")
            if not competitor_url:
                enriched_competitors.append(competitor)
                continue

            seo_data = self._extractor.extract_marketing_data(competitor_url)
            enriched_competitor = {**competitor, "seo_data": seo_data}
            enriched_competitors.append(enriched_competitor)

        return enriched_competitors + remaining_competitors

    def analyze_competitor_landscape(self, website_url: str, summary_text: str) -> dict[str, Any]:
        competitor_data = self.find_competitors_only(website_url, summary_text)
        enriched_competitors = self.enrich_competitors(competitor_data["competitors"])

        landscape_analysis = {
            "summary": {
                "total_competitors": len(enriched_competitors),
                "enriched_competitors": min(5, len(competitor_data["competitors"])),
                "query_processed": competitor_data["query_processed"],
                "target_company": competitor_data["target_company"],
            },
            "competitors": enriched_competitors,
        }

        return landscape_analysis

    def generate_marketing_recommendations(
        self, enriched_competitors: list[dict[str, Any]], target_company: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate marketing recommendations using OpenAI analysis of competitors."""
        if not enriched_competitors:
            return {"marketing_recommendations": "No competitors available for analysis", "status": "failed"}

        try:
            # Prepare competitive analysis data for the LLM
            analysis_data = {
                "target_company": {
                    "url": target_company.get("url", ""),
                    "description": target_company.get("description", ""),
                },
                "competitors": [],
            }

            # Include top 5 enriched competitors with their data
            for i, competitor in enumerate(enriched_competitors[:5]):
                competitor_data = {
                    "rank": i + 1,
                    "title": competitor.get("title", "Unknown Company"),
                    "url": competitor.get("url", ""),
                    "summary": competitor.get("summary", ""),
                    "score": competitor.get("score", 0),
                }

                # Add SEO data if available
                if "seo_data" in competitor:
                    seo = competitor["seo_data"]
                    competitor_data["seo_insights"] = {
                        "title": seo.get("title", ""),
                        "description": seo.get("description", ""),
                        "keywords": seo.get("keywords", [])[:10],  # Limit to top 10 keywords
                        "h1_tags": seo.get("h1_tags", [])[:5],  # Limit to first 5 H1s
                        "load_speed": seo.get("load_speed"),
                        "technologies": seo.get("technologies", [])[:10],  # Top 10 technologies
                    }

                analysis_data["competitors"].append(competitor_data)

            # Add remaining competitors without detailed analysis
            remaining_count = len(enriched_competitors) - 5
            if remaining_count > 0:
                analysis_data["additional_competitors_found"] = remaining_count

            # Call OpenAI for recommendations
            user_content = json.dumps(analysis_data, indent=2)

            logger.info(
                f"Generating marketing recommendations for {target_company.get('url')} with {len(analysis_data['competitors'])} detailed competitors"
            )

            llm_response = openai.chat.completions.create(
                model="gpt-4o-2024-08-06",
                temperature=0.3,  # Some creativity but focused. hopefully.
                messages=[
                    {"role": "system", "content": MARKETING_RECOMMENDATIONS_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                user="ph/marketing/recommendations",
                stream=False,
            )

            recommendations = llm_response.choices[0].message.content

            return {
                "marketing_recommendations": recommendations,
                "competitors_analyzed": len(enriched_competitors[:5]),
                "final_analysis": {
                    "total_competitors": len(enriched_competitors),
                    "enriched_count": min(5, len(enriched_competitors)),
                    "target_company": target_company,
                },
                "status": "completed",
            }

        except Exception as e:
            logger.exception(f"Error generating marketing recommendations: {e}")

            return {
                "marketing_recommendations": f"Could not generate AI-powered marketing recommendations due to technical error: {str(e)}",
                "competitors_analyzed": len(enriched_competitors[:5]),
                "final_analysis": {
                    "total_competitors": len(enriched_competitors),
                    "enriched_count": min(5, len(enriched_competitors)),
                    "target_company": target_company,
                },
                "status": "failed",
                "error": str(e),
            }


marketing_researcher_service = MarketingResearcherService()
