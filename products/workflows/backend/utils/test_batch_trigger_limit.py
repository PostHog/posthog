from django.test import TestCase, override_settings

from products.workflows.backend.utils.batch_trigger_limit import get_hogflow_batch_trigger_limit


class TestGetHogflowBatchTriggerLimit(TestCase):
    @override_settings(
        HOGFLOW_BATCH_TRIGGER_LIMIT=5000,
        HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED=50000,
        HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS={2, 99},
    )
    def test_returns_default_for_unlisted_team(self):
        assert get_hogflow_batch_trigger_limit(1) == 5000
        assert get_hogflow_batch_trigger_limit(7) == 5000

    @override_settings(
        HOGFLOW_BATCH_TRIGGER_LIMIT=5000,
        HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED=50000,
        HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS={2, 99},
    )
    def test_returns_elevated_for_listed_team(self):
        assert get_hogflow_batch_trigger_limit(2) == 50000
        assert get_hogflow_batch_trigger_limit(99) == 50000

    @override_settings(
        HOGFLOW_BATCH_TRIGGER_LIMIT=5000,
        HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED=50000,
        HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS=set(),
    )
    def test_returns_default_when_elevated_set_is_empty(self):
        assert get_hogflow_batch_trigger_limit(2) == 5000

    @override_settings(
        HOGFLOW_BATCH_TRIGGER_LIMIT=123,
        HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED=456,
        HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS={42},
    )
    def test_returns_currently_configured_values(self):
        # Doesn't snapshot 5000/50000 — picks up whatever the settings are at call time, so a
        # production tweak via env var is reflected immediately.
        assert get_hogflow_batch_trigger_limit(42) == 456
        assert get_hogflow_batch_trigger_limit(1) == 123
