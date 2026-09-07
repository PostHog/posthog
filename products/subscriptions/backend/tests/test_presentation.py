from __future__ import annotations

from products.subscriptions.backend.facade.research import PublicResearchCitation, PublicResearchResult
from products.subscriptions.backend.presentation.views import _response_payload


def test_research_response_payload_serializes_slotted_citations() -> None:
    payload = _response_payload(
        PublicResearchResult(
            citations=(
                PublicResearchCitation(
                    id="web:example",
                    url="https://example.com",
                    title="Example",
                    excerpt="Useful evidence.",
                ),
            )
        )
    )

    assert payload == {
        "citations": [
            {
                "id": "web:example",
                "url": "https://example.com",
                "title": "Example",
                "excerpt": "Useful evidence.",
            }
        ],
        "degradation": None,
    }
