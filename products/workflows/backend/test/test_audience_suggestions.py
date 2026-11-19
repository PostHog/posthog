from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.facade.contracts import AudienceKind, AudienceSuggestion
from products.workflows.backend.services.audience_suggestions.audience import sample_denominator
from products.workflows.backend.services.audience_suggestions.service import _PROMPT_EVENTS_LIMIT, prompt_events


class TestAudienceSampling(SimpleTestCase):
    @parameterized.expand(
        [
            ("quiet_project_counts_everyone", "regulars", 7, {"used": 500_000}, 1),
            ("busy_event_over_a_short_window", "regulars", 7, {"used": 100_000_000}, 10),
            ("lapsed_reads_90_days_whatever_its_window", "lapsed", 7, {"used": 7_000_000}, 9),
            ("event_without_a_count_adds_nothing", "regulars", 7, {}, 1),
        ]
    )
    def test_keeps_the_scan_small(
        self, _name: str, kind: AudienceKind, window_days: int, counts: dict[str, int], expected: int
    ) -> None:
        audience = AudienceSuggestion(
            id="1",
            name="Audience",
            description="",
            reason="",
            kind=kind,
            event="used",
            missing_event=None,
            window_days=window_days,
            min_count=None,
            reachable_count=None,
            cohort_filters={},
        )

        assert sample_denominator([audience], counts) == expected


class TestAudiencePromptEvents(SimpleTestCase):
    def test_quiet_feature_events_reach_the_prompt_past_busy_telemetry(self) -> None:
        counts = {f"telemetry {index}": 1_000_000 - index for index in range(_PROMPT_EVENTS_LIMIT * 2)}
        counts.update({"user signed up": 40, "dashboard created": 999_800, "query execution failed": 5_000_000})

        names = [name for name, _ in prompt_events(counts)]

        assert len(names) == _PROMPT_EVENTS_LIMIT
        assert names[0] == "user signed up"
        assert "dashboard created" in names
        assert "query execution failed" not in names
