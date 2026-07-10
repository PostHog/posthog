from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest

from django.utils import timezone

from products.replay_vision.backend.billing import (
    _FALLBACK_CREDITS,
    OBSERVATION_CREDITS_BY_MODEL,
    get_replay_vision_credits_by_team,
    observation_credits_for_model,
)
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_scanner import ScannerModel


class TestReplayVisionBillingUsage(APIBaseTest):
    def _receipt(
        self,
        *,
        team_id: int | None,
        created_at: datetime,
        model: str = ScannerModel.GEMINI_3_FLASH,
        credits: int | None = None,
    ) -> None:
        receipt = ReplayObservationUsage.objects.create(
            observation_id=uuid4(),
            organization_id=self.organization.id,
            team_id=team_id,
            observation_created_at=created_at,
            model=model,
            credits=credits if credits is not None else observation_credits_for_model(model),
        )
        # created_at is auto_now_add, so set it explicitly to control the billing window.
        ReplayObservationUsage.objects.filter(pk=receipt.pk).update(created_at=created_at)

    def test_sums_credits_per_team_within_window_by_created_at(self) -> None:
        now = timezone.now()
        begin = now - timedelta(days=1)
        end = now + timedelta(days=1)
        # Two in-window at different model prices, one out-of-window, one for another team.
        self._receipt(team_id=self.team.id, created_at=now, model=ScannerModel.GEMINI_3_FLASH)
        self._receipt(team_id=self.team.id, created_at=now, model=ScannerModel.GEMINI_3_5_FLASH)
        self._receipt(team_id=self.team.id, created_at=now - timedelta(days=3))
        self._receipt(team_id=self.team.id + 1, created_at=now, model=ScannerModel.GEMINI_2_5_FLASH)

        result = dict(get_replay_vision_credits_by_team(begin, end))
        assert result == {self.team.id: 5 + 15, self.team.id + 1: 2}

    def test_sums_frozen_receipt_credits_not_live_prices(self) -> None:
        # A receipt priced before a table change keeps billing at its frozen amount.
        now = timezone.now()
        self._receipt(team_id=self.team.id, created_at=now, credits=7)
        result = get_replay_vision_credits_by_team(now - timedelta(hours=1), now + timedelta(hours=1))
        assert result == [(self.team.id, 7)]

    def test_excludes_legacy_receipts_without_team(self) -> None:
        now = timezone.now()
        self._receipt(team_id=None, created_at=now)
        self._receipt(team_id=self.team.id, created_at=now)

        result = get_replay_vision_credits_by_team(now - timedelta(hours=1), now + timedelta(hours=1))
        assert result == [(self.team.id, 5)]

    def test_window_is_end_exclusive(self) -> None:
        boundary = datetime(2026, 7, 1, tzinfo=UTC)
        self._receipt(team_id=self.team.id, created_at=boundary)
        result = get_replay_vision_credits_by_team(boundary - timedelta(days=1), boundary)
        assert result == []

    def test_unknown_model_bills_at_highest_known_price(self) -> None:
        assert observation_credits_for_model("gemini-99-ultra") == _FALLBACK_CREDITS
        assert _FALLBACK_CREDITS == max(OBSERVATION_CREDITS_BY_MODEL.values())


def test_every_scanner_model_has_a_credit_price() -> None:
    # A new ScannerModel member without a price would bill at the max fallback; catch it at PR time.
    unpriced = set(ScannerModel.values) - set(OBSERVATION_CREDITS_BY_MODEL)
    assert not unpriced, f"ScannerModel members missing from OBSERVATION_CREDITS_BY_MODEL: {unpriced}"
