from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.person_property_phase_timer import (
    PhaseTimer,
)


class TestPhaseTimer:
    def test_each_batch_reports_only_its_own_time_and_the_run_reports_all_of_it(self):
        timer = PhaseTimer("backfill")
        timer.add("read_key_pass", 4.0)
        timer.take_batch_fields()

        timer.add("read", 1.0)
        timer.add("existence_lookup", 2.0)
        timer.add("existence_lookup", 0.5)
        first_batch = timer.take_batch_fields()
        timer.add("read", 0.25)
        second_batch = timer.take_batch_fields()
        timer.add("compaction", 3.0)
        run = timer.run_fields()

        assert first_batch == {"read_ms": 1000, "existence_lookup_ms": 2500}
        assert second_batch == {"read_ms": 250}
        assert {key: run[key] for key in ("read_key_pass_ms", "read_ms", "existence_lookup_ms", "compaction_ms")} == {
            "read_key_pass_ms": 4000,
            "read_ms": 1250,
            "existence_lookup_ms": 2500,
            "compaction_ms": 3000,
        }
