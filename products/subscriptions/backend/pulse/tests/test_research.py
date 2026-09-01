from django.test import SimpleTestCase

from products.subscriptions.backend.pulse.research import (
    PUBLIC_RESEARCH_TOPIC_QUERIES,
    PUBLIC_RESEARCH_TOPICS,
    PublicResearchValidationError,
    public_research_query_for_topic,
)


class TestPublicResearchContract(SimpleTestCase):
    def test_every_available_topic_maps_to_a_fixed_query(self) -> None:
        assert set(PUBLIC_RESEARCH_TOPICS) == set(PUBLIC_RESEARCH_TOPIC_QUERIES)
        assert public_research_query_for_topic("activation_best_practices") == (
            "software product activation best practices"
        )

    def test_rejects_model_authored_text_instead_of_forwarding_it(self) -> None:
        with self.assertRaises(PublicResearchValidationError):
            public_research_query_for_topic("Research person@example.com with internal report details")
