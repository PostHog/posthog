from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from products.signals.backend.facade.api import latest_structured_output_for_source
from products.signals.backend.models import SignalScoutConfig

_SOURCE_PRODUCT = "replay_vision"
_TAG = "variant-analysis"


class TestLatestStructuredOutputForSource(ClickhouseTestMixin, APIBaseTest):
    def _scout(self, skill_name: str, *, source_id: str, tags: list[str]) -> None:
        SignalScoutConfig.objects.for_team(self.team.id).create(
            team=self.team, skill_name=skill_name, source_product=_SOURCE_PRODUCT, source_id=source_id, tags=tags
        )

    def _record(self, skill_name: str, payload: dict, *, minutes_after: int) -> None:
        # After the configs: no record can predate its scout, and the read is bounded below by that.
        _create_event(
            team=self.team,
            event="$scout_structured_output",
            distinct_id="signals-scout",
            timestamp=timezone.now() + timedelta(minutes=minutes_after),
            properties={"skill_name": skill_name, "run_id": f"run-{skill_name}-{minutes_after}", "output": payload},
        )

    def test_returns_the_newest_record_of_the_sources_tagged_scouts_only(self) -> None:
        self._scout("signals-scout-analysis", source_id="scanner-a", tags=[_TAG])
        self._scout("signals-scout-digest", source_id="scanner-a", tags=[])
        self._scout("signals-scout-other-analysis", source_id="scanner-b", tags=[_TAG])
        self._record("signals-scout-analysis", {"scanner_version": 1}, minutes_after=1)
        self._record("signals-scout-analysis", {"scanner_version": 2}, minutes_after=2)
        # Newer, but from an untagged scout on the same source and a tagged scout on another source.
        self._record("signals-scout-digest", {"scanner_version": 9}, minutes_after=3)
        self._record("signals-scout-other-analysis", {"scanner_version": 9}, minutes_after=3)
        flush_persons_and_events()

        record = latest_structured_output_for_source(self.team.id, _SOURCE_PRODUCT, "scanner-a", tag=_TAG)

        assert record is not None
        assert record.payload == {"scanner_version": 2}
        assert record.skill_name == "signals-scout-analysis"
        assert record.run_id == "run-signals-scout-analysis-2"
        assert latest_structured_output_for_source(self.team.id, _SOURCE_PRODUCT, "scanner-c", tag=_TAG) is None
