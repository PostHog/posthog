"""Bills replay vision credits from the immutable `ReplayObservationUsage` receipt ledger, the same source the in-product quota meter reads.

Credits use the same unit as ai_credits: 1 credit = $0.01. Each observation costs a
model-dependent number of credits, frozen onto its receipt at success time so later
price changes never reprice history.
"""

from datetime import datetime
from typing import cast

from django.db.models import IntegerField, Sum
from django.db.models.functions import Coalesce

import structlog

from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_scanner import ScannerModel

logger = structlog.get_logger(__name__)

CREDITS_PER_DOLLAR = 100  # 1 credit = $0.01, matching ai_credits

# Keyed on the raw model-id string (not the enum) because frozen `scanner_snapshot`s and
# receipts outlive enum members; retired ids must keep pricing in-flight observations.
OBSERVATION_CREDITS_BY_MODEL: dict[str, int] = {
    ScannerModel.GEMINI_2_5_FLASH: 2,
    ScannerModel.GEMINI_3_FLASH: 5,
    ScannerModel.GEMINI_3_5_FLASH: 15,
    # Retired ids, kept for observations frozen before the lineup change.
    "gemini-3.1-flash-lite-preview": 2,
}

# Unknown models bill at the highest known price: never underbill on a mapping gap.
_FALLBACK_CREDITS = max(OBSERVATION_CREDITS_BY_MODEL.values())


def observation_credits_for_model(model: str) -> int:
    credits = OBSERVATION_CREDITS_BY_MODEL.get(model)
    if credits is None:
        logger.warning("replay_vision.unknown_model_credits", model=model, fallback=_FALLBACK_CREDITS)
        return _FALLBACK_CREDITS
    return credits


def get_replay_vision_credits_by_team(begin: datetime, end: datetime) -> list[tuple[int, int]]:
    # Bucket by receipt write time so a late receipt is never dropped from an already-run daily report.
    rows = (
        ReplayObservationUsage.objects.filter(created_at__gte=begin, created_at__lt=end, team_id__isnull=False)
        .values("team_id")
        .annotate(total_credits=Coalesce(Sum("credits"), 0, output_field=IntegerField()))
        .values_list("team_id", "total_credits")
    )
    return cast(list[tuple[int, int]], list(rows))
