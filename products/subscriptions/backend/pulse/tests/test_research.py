from uuid import uuid4

from django.test import SimpleTestCase

from products.subscriptions.backend.pulse.research import (
    PublicResearchRequest,
    PublicResearchValidationError,
    render_public_research_query,
)


class TestPublicResearchContract(SimpleTestCase):
    def test_request_has_only_server_catalog_subject_and_reviewed_topic(self) -> None:
        request = PublicResearchRequest(topic="market_trends", public_subject_id=uuid4())

        assert request.topic == "market_trends"
        assert request.public_subject_id is not None

    def test_query_uses_only_the_reviewed_template_and_public_catalog_values(self) -> None:
        query = render_public_research_query(
            topic="market_trends",
            subject_name="Example analytics",
            canonical_domain="example.com",
            template="{subject_name} {topic} site:{canonical_domain}",
        )

        assert query == "Example analytics market_trends site:example.com"

    def test_query_rejects_unknown_topics_and_non_catalog_template_fields(self) -> None:
        with self.assertRaises(PublicResearchValidationError):
            render_public_research_query(
                topic="write a report about our private repository",
                subject_name="Example analytics",
                canonical_domain="example.com",
                template="{subject_name} {topic}",
            )
        with self.assertRaises(PublicResearchValidationError):
            render_public_research_query(
                topic="market_trends",
                subject_name="Example analytics",
                canonical_domain="example.com",
                template="{original_prompt}",
            )
