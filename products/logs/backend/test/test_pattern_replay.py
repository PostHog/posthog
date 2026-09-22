import json
import datetime as dt
import tempfile
from dataclasses import replace
from pathlib import Path

from unittest import TestCase

from parameterized import parameterized

from products.logs.backend.log_patterns import LogSample
from products.logs.backend.pattern_replay import (
    ReplayConfig,
    ReplayReport,
    count_prefix_duplicates,
    diff_reports,
    load_corpus,
    main,
    measure,
)

_T0 = dt.datetime(2026, 8, 14, 12, 0, tzinfo=dt.UTC)
_SAMPLE_CORPUS = Path(__file__).parent / "fixtures" / "pattern_replay_sample.jsonl"


def _sample(body: str, service: str = "svc") -> LogSample:
    return LogSample(body=body, severity_text="info", service_name=service, timestamp=_T0)


_BASE_CONFIG = ReplayConfig(truncate=512, sim_th=0.4, depth=4, max_clusters=1000)


def _report(templates: int, prefix_dupes: int, config: ReplayConfig = _BASE_CONFIG) -> ReplayReport:
    return ReplayReport(
        sample_count=1000,
        template_count=templates,
        prefix_duplicate_count=prefix_dupes,
        config=config,
    )


class TestPatternReplay(TestCase):
    @parameterized.expand(
        [
            ("a lone template is not its own prefix", ["a b c"], 0),
            ("equal templates are not strict prefixes", ["a b", "a b"], 0),
            ("the prefix is counted, not its extensions", ["x", "xa", "xb"], 1),
            ("every link in a chain counts once", ["x", "xa", "xab"], 2),
            ("unrelated templates never match", ["alpha", "beta"], 0),
            ("an empty corpus counts nothing", [], 0),
        ]
    )
    def test_count_prefix_duplicates(self, _name: str, templates: list[str], expected: int) -> None:
        self.assertEqual(count_prefix_duplicates(templates), expected)

    def test_measure_counts_mined_templates_not_raw_bodies(self) -> None:
        samples = [_sample(f"connected to 10.0.0.{i} in {i} ms") for i in range(20)]

        report = measure(samples)

        self.assertEqual(report.sample_count, 20)
        self.assertEqual(report.template_count, 1)

    def test_measure_sees_past_the_api_display_cap(self) -> None:
        # Unique literal tokens and a spread of token counts, so Drain cannot merge these
        # into each other and the corpus really does hold more than the 200-row display cap.
        samples = [_sample(" ".join(f"tok{i}x{k}" for k in range(3 + i % 40))) for i in range(320)]

        report = measure(samples)

        self.assertGreater(report.template_count, 200)

    def test_measure_scores_each_service_on_its_own_bodies(self) -> None:
        one_shape = [_sample(f"cache hit for key 10.0.0.{i}", service="alpha") for i in range(10)]
        many_shapes = [_sample(" ".join(f"w{i}x{k}" for k in range(3 + i % 12)), service="beta") for i in range(10)]

        report = measure(one_shape + many_shapes)

        by_name = {service.service_name: service for service in report.services}
        self.assertEqual(by_name["alpha"].sample_count, 10)
        self.assertEqual(by_name["alpha"].template_count, 1)
        self.assertGreater(by_name["beta"].template_count, 1)

    def test_measure_records_the_config_it_ran_under(self) -> None:
        report = measure([_sample("anything at all")])

        self.assertEqual(report.config, _BASE_CONFIG)

    def test_diff_subtracts_candidate_from_baseline(self) -> None:
        diff = diff_reports(_report(templates=426, prefix_dupes=106), _report(templates=263, prefix_dupes=35))

        self.assertEqual(diff.config_mismatch, ())
        self.assertEqual(diff.template_delta, -163)
        self.assertEqual(diff.prefix_duplicate_delta, -71)

    @parameterized.expand(
        [
            ("truncate", replace(_BASE_CONFIG, truncate=1024)),
            ("sim_th", replace(_BASE_CONFIG, sim_th=0.6)),
            ("depth", replace(_BASE_CONFIG, depth=6)),
            ("max_clusters", replace(_BASE_CONFIG, max_clusters=5000)),
        ]
    )
    def test_diff_flags_reports_mined_under_different_config(self, field: str, changed: ReplayConfig) -> None:
        baseline = _report(templates=426, prefix_dupes=106)
        candidate = _report(templates=263, prefix_dupes=35, config=changed)

        diff = diff_reports(baseline, candidate)

        self.assertEqual(diff.config_mismatch, (field,))

    def test_load_corpus_keeps_bodies_whole(self) -> None:
        multiline = 'Traceback:\n  File "app.py", line 3\n    raise ValueError("boom")'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corpus.jsonl"
            path.write_text(
                json.dumps({"body": multiline, "service_name": "checkout"})
                + "\n\n"
                + json.dumps({"body": "plain line"})
                + "\n"
            )

            samples = load_corpus(path)

        self.assertEqual([s.body for s in samples], [multiline, "plain line"])
        self.assertEqual(samples[0].service_name, "checkout")

    def test_cli_runs_without_crashing(self) -> None:
        main([str(_SAMPLE_CORPUS), "--compare", "truncate=1024"])

    @parameterized.expand(
        [
            ("no value at all", "truncate"),
            ("an empty value", "truncate="),
            ("a word where a number belongs", "truncate=abc"),
            ("a fraction for a whole-number knob", "truncate=1.5"),
            ("a word where a fraction belongs", "sim_th=abc"),
            ("a knob that does not exist", "nonsense=1"),
        ]
    )
    def test_cli_refuses_an_override_it_cannot_apply(self, _name: str, pair: str) -> None:
        with self.assertRaises(SystemExit):
            main([str(_SAMPLE_CORPUS), "--compare", pair])
