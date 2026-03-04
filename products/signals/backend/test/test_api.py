import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pydantic

from products.signals.backend.api import emit_signal


@pytest.fixture
def team_stub() -> MagicMock:
    org = MagicMock()
    org.is_ai_data_processing_approved = True
    team = MagicMock()
    team.id = 1
    team.organization = org
    return team


SESSION_SEGMENT_CLUSTER_EXTRA = {
    "label_title": "Frustrated users on checkout",
    "actionable": True,
    "segments": [
        {
            "session_id": "abc-123",
            "start_time": "2025-01-01T00:00:00Z",
            "end_time": "2025-01-01T00:05:00Z",
            "distinct_id": "user-1",
            "content": "User clicked around and rage-clicked the submit button",
        }
    ],
    "metrics": {
        "relevant_user_count": 42,
        "active_users_in_period": 1000,
        "occurrence_count": 7,
    },
}

EVALUATION_EXTRA = {
    "evaluation_id": "eval-001",
    "trace_id": "trace-abc",
}

ZENDESK_TICKET_EXTRA = {
    "url": "https://example.zendesk.com/tickets/1",
    "type": "problem",
    "tags": ["billing", "urgent"],
    "created_at": "2025-06-01T12:00:00Z",
    "priority": "high",
    "status": "open",
}

GITHUB_ISSUE_EXTRA = {
    "html_url": "https://github.com/org/repo/issues/42",
    "number": 42,
    "labels": ["bug", "critical"],
    "created_at": "2025-06-01T12:00:00Z",
    "updated_at": "2025-06-02T08:00:00Z",
    "locked": False,
    "state": "open",
}


@pytest.mark.asyncio
class TestEmitSignalValidation:
    @pytest.mark.parametrize(
        "source_product, source_type, extra",
        [
            ("session_replay", "session_segment_cluster", SESSION_SEGMENT_CLUSTER_EXTRA),
            ("llm_analytics", "evaluation", EVALUATION_EXTRA),
            ("zendesk", "ticket", ZENDESK_TICKET_EXTRA),
            ("github", "issue", GITHUB_ISSUE_EXTRA),
        ],
        ids=["session_segment_cluster", "evaluation", "ticket", "issue"],
    )
    async def test_emit_signal_accepts_valid_input(self, source_product, source_type, extra, team_stub):
        client = AsyncMock()

        with patch("products.signals.backend.api.async_connect", return_value=client):
            await emit_signal(
                team=team_stub,
                source_product=source_product,
                source_type=source_type,
                source_id="test-id-1",
                description="A valid signal",
                extra=extra,
            )

        client.start_workflow.assert_awaited_once()

    @pytest.mark.parametrize(
        "source_product, source_type, extra",
        [
            ("session_replay", "nonexistent", {}),
            ("github", "issue", {}),
            ("zendesk", "ticket", {**ZENDESK_TICKET_EXTRA, "tags": "not-a-list"}),
            ("llm_analytics", "evaluation", {**EVALUATION_EXTRA, "bogus": 1}),
        ],
        ids=["unknown_source_type", "missing_extra_fields", "wrong_extra_field_type", "unexpected_extra_field"],
    )
    async def test_emit_signal_rejects_invalid_input(self, source_product, source_type, extra, team_stub):
        client = AsyncMock()

        with patch("products.signals.backend.api.async_connect", return_value=client):
            with pytest.raises(pydantic.ValidationError):
                await emit_signal(
                    team=team_stub,
                    source_product=source_product,
                    source_type=source_type,
                    source_id="test-id-1",
                    description="An invalid signal",
                    extra=extra,
                )

        client.start_workflow.assert_not_awaited()
