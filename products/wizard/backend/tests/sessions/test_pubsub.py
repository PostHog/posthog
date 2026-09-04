from datetime import UTC, datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import transaction

from redis.exceptions import ConnectionError as RedisConnectionError

from products.wizard.backend.facade.contracts import WizardSessionDTO, WizardTaskDTO
from products.wizard.backend.facade.enums import WizardSessionRunPhase, WizardSessionTaskStatus
from products.wizard.backend.logic.sessions.pubsub import channel_name, publish_session_update, subscribe
from products.wizard.backend.logic.sessions.validation import validate_channel_identifier


def _dto(team_id: int = 1) -> WizardSessionDTO:
    now = datetime(2026, 5, 19, 10, 0, 0, tzinfo=UTC)
    return WizardSessionDTO(
        # session_id has no colons because channel_name validates the safe-id
        # alphabet on workflow_id/skill_id. session_id itself isn't part of
        # the channel name, but we still keep the format safe for downstream
        # consumers.
        session_id="onboarding-nextjs-2026-05-19T10-00-00Z",
        team_id=team_id,
        workflow_id="onboarding",
        skill_id="nextjs",
        started_at=now,
        run_phase=WizardSessionRunPhase.RUNNING,
        is_stale=False,
        tasks=(WizardTaskDTO(id="1", title="Install SDK", status=WizardSessionTaskStatus.IN_PROGRESS),),
        event_plan=None,
        error=None,
        pending_input=None,
        handoff_text=None,
        created_by=None,
        created_at=now,
        updated_at=now,
    )


def test_channel_name_is_deterministic():
    assert channel_name(1, "onboarding", "nextjs") == "wizard_sessions:team:1:workflow:onboarding:skill:nextjs"


def test_channel_name_rejects_unsafe_ids():
    """workflow_id / skill_id can't smuggle Redis glob metacharacters or `:`."""
    with pytest.raises(ValueError):
        channel_name(1, "onboarding", "next*")
    with pytest.raises(ValueError):
        channel_name(1, "*", "nextjs")
    with pytest.raises(ValueError):
        channel_name(1, "onboarding:malicious", "nextjs")
    with pytest.raises(ValueError):
        channel_name(1, "onboarding", "next[js]")


def test_channel_identifier_accepts_safe_values() -> None:
    validate_channel_identifier("onboarding", "workflow_id")


@pytest.mark.django_db(transaction=True)
def test_publish_session_update_publishes_after_commit():
    """In transaction.atomic, the publish should defer to on_commit."""
    redis_mock = MagicMock()
    with patch("products.wizard.backend.logic.sessions.pubsub.get_client", return_value=redis_mock):
        with transaction.atomic():
            publish_session_update(_dto())
            assert redis_mock.publish.call_count == 0  # not yet committed

        # After atomic block exits, on_commit hooks fire.
        assert redis_mock.publish.call_count == 1
        channel, payload = redis_mock.publish.call_args.args
        assert channel == "wizard_sessions:team:1:workflow:onboarding:skill:nextjs"
        assert b'"session_id":"onboarding-nextjs-2026-05-19T10-00-00Z"' in payload
        assert b'"run_phase":"running"' in payload
        assert b'"status":"in_progress"' in payload


@pytest.mark.django_db
def test_publish_session_update_does_not_publish_on_rollback():
    redis_mock = MagicMock()
    with patch("products.wizard.backend.logic.sessions.pubsub.get_client", return_value=redis_mock):
        try:
            with transaction.atomic():
                publish_session_update(_dto())
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass

        assert redis_mock.publish.call_count == 0


@pytest.mark.django_db(transaction=True)
def test_publish_session_update_swallows_redis_errors():
    """Redis publish failure must not fail the upsert request."""
    redis_mock = MagicMock()
    redis_mock.publish.side_effect = RedisConnectionError("redis is down")

    with patch("products.wizard.backend.logic.sessions.pubsub.get_client", return_value=redis_mock):
        with transaction.atomic():
            publish_session_update(_dto())
        # If the exception escaped on_commit, this assertion wouldn't run.
        assert redis_mock.publish.call_count == 1


@pytest.mark.asyncio
async def test_subscribe_closes_pubsub_when_subscription_has_programming_error() -> None:
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock(side_effect=RuntimeError("bug"))
    pubsub.close = AsyncMock()
    redis = MagicMock()
    redis.pubsub.return_value = pubsub

    with (
        patch("products.wizard.backend.logic.sessions.pubsub.get_async_client", return_value=redis),
        pytest.raises(RuntimeError, match="bug"),
    ):
        async with subscribe(1, "onboarding", "nextjs"):
            pass

    pubsub.close.assert_awaited_once_with()
