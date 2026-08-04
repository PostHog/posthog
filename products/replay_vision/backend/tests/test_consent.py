import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import OperationalError

from products.replay_vision.backend.temporal.consent import is_ai_data_processing_approved_resilient


class TestIsAiDataProcessingApprovedResilient:
    @pytest.mark.asyncio
    async def test_returns_result_without_retrying_on_success(self) -> None:
        with (
            patch(
                "products.replay_vision.backend.temporal.consent.is_ai_data_processing_approved", return_value=True
            ) as mock_check,
            patch(
                "products.replay_vision.backend.temporal.consent.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep,
        ):
            assert await is_ai_data_processing_approved_resilient(team_id=1) is True
        assert mock_check.call_count == 1
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_absorbs_a_transient_db_error_and_succeeds(self) -> None:
        # A PgBouncer blip on the first attempt must not fail the consent check outright — it should
        # be retried inline rather than consuming one of the caller's own (much more expensive) attempts.
        mock_check = MagicMock(side_effect=[OperationalError("query_wait_timeout"), True])
        with (
            patch("products.replay_vision.backend.temporal.consent.is_ai_data_processing_approved", mock_check),
            patch("products.replay_vision.backend.temporal.consent.asyncio.sleep", new_callable=AsyncMock),
        ):
            assert await is_ai_data_processing_approved_resilient(team_id=1) is True
        assert mock_check.call_count == 2

    @pytest.mark.asyncio
    async def test_reraises_once_transient_retries_are_exhausted(self) -> None:
        mock_check = MagicMock(side_effect=OperationalError("query_wait_timeout"))
        with (
            patch("products.replay_vision.backend.temporal.consent.is_ai_data_processing_approved", mock_check),
            patch("products.replay_vision.backend.temporal.consent.asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(OperationalError):
                await is_ai_data_processing_approved_resilient(team_id=1)
        assert mock_check.call_count == 3

    @pytest.mark.asyncio
    async def test_does_not_retry_a_non_transient_error(self) -> None:
        # A genuine query bug must fail immediately, not be masked behind three silent retries.
        mock_check = MagicMock(side_effect=OperationalError('relation "foo" does not exist'))
        with (
            patch("products.replay_vision.backend.temporal.consent.is_ai_data_processing_approved", mock_check),
            patch(
                "products.replay_vision.backend.temporal.consent.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep,
        ):
            with pytest.raises(OperationalError):
                await is_ai_data_processing_approved_resilient(team_id=1)
        assert mock_check.call_count == 1
        mock_sleep.assert_not_called()
