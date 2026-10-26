import uuid
from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.apps import apps

from products.signals.backend.facade.api import latest_structured_output_for_source
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun

_SOURCE_PRODUCT = "replay_vision"
_TAG = "variant-analysis"


class TestLatestStructuredOutputForSource(ClickhouseTestMixin, APIBaseTest):
    def _scout(self, skill_name: str, *, source_id: str, tags: list[str]) -> SignalScoutConfig:
        return SignalScoutConfig.objects.for_team(self.team.id).create(
            team=self.team, skill_name=skill_name, source_product=_SOURCE_PRODUCT, source_id=source_id, tags=tags
        )

    def _run(self, config: SignalScoutConfig) -> SignalScoutRun:
        task = apps.get_model("tasks", "Task").objects.create(team=self.team, title="scout", description="d")
        task_run = apps.get_model("tasks", "TaskRun").objects.create(team=self.team, task=task)
        return SignalScoutRun.objects.for_team(self.team.id).create(
            team=self.team, task_run=task_run, scout_config=config, skill_name=config.skill_name, skill_version=1
        )

    def _record(self, skill_name: str, run_id: str, payload: dict | str, *, at) -> None:
        _create_event(
            team=self.team,
            event="$scout_structured_output",
            distinct_id=f"signals_scout:{skill_name}",
            timestamp=at,
            properties={"skill_name": skill_name, "run_id": run_id, "output": payload},
        )

    def test_returns_the_newest_record_of_a_real_run_of_the_sources_tagged_scouts(self) -> None:
        analysis = self._scout("signals-scout-analysis", source_id="scanner-a", tags=[_TAG])
        digest = self._scout("signals-scout-digest", source_id="scanner-a", tags=[])
        elsewhere = self._scout("signals-scout-other-analysis", source_id="scanner-b", tags=[_TAG])
        first, second = self._run(analysis), self._run(analysis)
        self._record(analysis.skill_name, str(first.id), {"scanner_version": 1}, at=first.created_at)
        self._record(analysis.skill_name, str(second.id), {"scanner_version": 2}, at=second.created_at)
        # Real runs, but of an untagged scout on the same source and a tagged scout on another source.
        for config in (digest, elsewhere):
            run = self._run(config)
            self._record(config.skill_name, str(run.id), {"scanner_version": 9}, at=run.created_at)
        # Sent with the public capture token: a run id no scout ran, and a real run id with a later
        # timestamp than the run's start, which would otherwise sort first.
        self._record(analysis.skill_name, str(uuid.uuid4()), {"scanner_version": 9}, at=second.created_at)
        self._record(
            analysis.skill_name, str(second.id), {"scanner_version": 9}, at=second.created_at + timedelta(hours=12)
        )
        flush_persons_and_events()

        record = latest_structured_output_for_source(self.team.id, _SOURCE_PRODUCT, "scanner-a", tag=_TAG)

        assert record is not None
        assert record.payload == {"scanner_version": 2}
        assert (record.run_id, record.skill_name) == (str(second.id), analysis.skill_name)
        assert latest_structured_output_for_source(self.team.id, _SOURCE_PRODUCT, "scanner-c", tag=_TAG) is None

    def test_skips_a_malformed_record_and_returns_an_older_valid_one(self) -> None:
        analysis = self._scout("signals-scout-analysis", source_id="scanner-a", tags=[_TAG])
        first, second = self._run(analysis), self._run(analysis)
        self._record(analysis.skill_name, str(first.id), {"scanner_version": 1}, at=first.created_at)
        self._record(analysis.skill_name, str(second.id), "{not json", at=second.created_at)
        flush_persons_and_events()

        record = latest_structured_output_for_source(self.team.id, _SOURCE_PRODUCT, "scanner-a", tag=_TAG)

        assert record is not None
        assert record.payload == {"scanner_version": 1}
        assert record.run_id == str(first.id)
