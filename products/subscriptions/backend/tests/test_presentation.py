from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from products.subscriptions.backend.facade.contracts import PublicResearchCitation, PublicResearchResult
from products.subscriptions.backend.presentation import views
from products.subscriptions.backend.presentation.views import PulseResearchViewSet, _response_payload


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


@pytest.mark.parametrize("disabled_setting", ["PULSE_PROACTIVE_ENABLED", "PULSE_PUBLIC_RESEARCH_ENABLED"])
def test_runtime_kill_switch_blocks_an_existing_research_token(disabled_setting: str, settings, monkeypatch) -> None:
    settings.PULSE_PROACTIVE_ENABLED = disabled_setting != "PULSE_PROACTIVE_ENABLED"
    settings.PULSE_PUBLIC_RESEARCH_ENABLED = disabled_setting != "PULSE_PUBLIC_RESEARCH_ENABLED"
    request = Request(
        APIRequestFactory().post("/", {"query": "checkout trends"}, format="json"), parsers=[JSONParser()]
    )
    monkeypatch.setattr(
        views,
        "get_oauth_access_token",
        lambda _request: SimpleNamespace(scope="pulse_research_internal:read", sandbox_task_id=uuid4()),
    )
    monkeypatch.setattr(views, "run_public_research", lambda _query: PublicResearchResult(citations=()))

    search = cast(Callable[..., Response], PulseResearchViewSet().search)
    with pytest.raises(PermissionDenied):
        search(request, team_id=1)
