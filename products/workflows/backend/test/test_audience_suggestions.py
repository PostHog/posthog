from django.test import SimpleTestCase

from products.workflows.backend.services.audience_suggestions.service import _PROMPT_EVENTS_LIMIT, prompt_events


class TestAudiencePromptEvents(SimpleTestCase):
    def test_quiet_feature_events_reach_the_prompt_past_busy_telemetry(self) -> None:
        counts = {f"telemetry {index}": 1_000_000 - index for index in range(_PROMPT_EVENTS_LIMIT * 2)}
        counts.update({"user signed up": 40, "dashboard created": 999_800, "query execution failed": 5_000_000})

        names = [name for name, _ in prompt_events(counts)]

        assert len(names) == _PROMPT_EVENTS_LIMIT
        assert names[0] == "user signed up"
        assert "dashboard created" in names
        assert "query execution failed" not in names
