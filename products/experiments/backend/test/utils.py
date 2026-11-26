from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

from unittest.mock import patch

from django.test import override_settings

# Tests run as a self-hosted deployment with no cutoff, so a test sets one with override_exposure_event_cutoff.
EXPERIMENT_EXPOSURE_EVENT_CUTOFF = datetime(2026, 9, 1, tzinfo=UTC)


def override_exposure_event_cutoff(*, enabled: bool) -> override_settings:
    """Sets settings.EXPERIMENT_EXPOSURE_EVENT_CUTOFF as PostHog Cloud does, or unsets it as other deployments do."""
    return override_settings(EXPERIMENT_EXPOSURE_EVENT_CUTOFF=EXPERIMENT_EXPOSURE_EVENT_CUTOFF if enabled else None)


def patch_calculation_key_version(key_version: int) -> AbstractContextManager[Any]:
    """Makes every new operation use this calculation key version, as the activation decision would."""
    return patch(
        "products.experiments.backend.metric_calculation.config.resolve_calculation_key_version",
        return_value=key_version,
    )
