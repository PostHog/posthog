from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from django.db import transaction

from products.wizard.backend.facade.contracts import WizardSessionDTO, WizardTaskDTO
from products.wizard.backend.facade.enums import RunPhase, TaskStatus
from products.wizard.backend.logic.pubsub import channel_name, publish_session_update


def _dto(team_id: int = 1) -> WizardSessionDTO:
    now = datetime(2026, 5, 19, 10, 0, 0, tzinfo=UTC)
    return WizardSessionDTO(
        session_id="onboarding-nextjs-2026-05-19T10:00:00Z",
        team_id=team_id,
        workflow_id="onboarding",
        skill_id="nextjs",
        started_at=now,
        run_phase=RunPhase.RUNNING,
        tasks=(WizardTaskDTO(id="1", title="Install SDK", status=TaskStatus.IN_PROGRESS),),
        event_plan=None,
        error=None,
        created_at=now,
        updated_at=now,
    )


def test_channel_name_is_deterministic():
    assert channel_name(1, "onboarding", "nextjs") == "wizard_sessions:team:1:workflow:onboarding:skill:nextjs"


@pytest.mark.django_db(transaction=True)
def test_publish_session_update_publishes_after_commit():
    """In transaction.atomic, the publish should defer to on_commit."""
    redis_mock = MagicMock()
    with patch("products.wizard.backend.logic.pubsub.get_client", return_value=redis_mock):
        with transaction.atomic():
            publish_session_update(_dto())
            assert redis_mock.publish.call_count == 0  # not yet committed

        # After atomic block exits, on_commit hooks fire.
        assert redis_mock.publish.call_count == 1
        channel, payload = redis_mock.publish.call_args.args
        assert channel == "wizard_sessions:team:1:workflow:onboarding:skill:nextjs"
        assert b'"session_id":"onboarding-nextjs-2026-05-19T10:00:00Z"' in payload
        assert b'"run_phase":"running"' in payload
        assert b'"status":"in_progress"' in payload


@pytest.mark.django_db
def test_publish_session_update_does_not_publish_on_rollback():
    redis_mock = MagicMock()
    with patch("products.wizard.backend.logic.pubsub.get_client", return_value=redis_mock):
        try:
            with transaction.atomic():
                publish_session_update(_dto())
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass

        assert redis_mock.publish.call_count == 0
