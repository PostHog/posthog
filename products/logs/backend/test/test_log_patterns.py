import datetime as dt

from unittest import TestCase

from parameterized import parameterized

from products.logs.backend.log_patterns import LogSample, mine_patterns


def _sample(
    body: str,
    severity: str = "info",
    service: str = "api",
    ts: dt.datetime | None = None,
) -> LogSample:
    return LogSample(
        body=body,
        severity_text=severity,
        service_name=service,
        timestamp=ts or dt.datetime(2026, 6, 23, 12, 0, 0, tzinfo=dt.UTC),
    )


class TestMinePatterns(TestCase):
    def test_merges_messages_differing_by_one_word_into_one_template(self) -> None:
        samples = [
            _sample("User alice not found"),
            _sample("User bob not found"),
            _sample("User carol not found"),
        ]

        patterns = mine_patterns(samples)

        assert len(patterns) == 1
        assert patterns[0].count == 3
        assert "User" in patterns[0].pattern
        assert "not found" in patterns[0].pattern
        # the varying token is collapsed to a wildcard, not preserved verbatim
        assert "alice" not in patterns[0].pattern
        assert "<*>" in patterns[0].pattern

    @parameterized.expand(
        [
            ("numbers", ["Request 123 took 5 ms", "Request 456 took 9 ms"], "<num>", "123"),
            ("ipv4", ["GET from 10.0.0.1", "GET from 192.168.1.1"], "<ip>", "10.0.0.1"),
            (
                "uuid",
                [
                    "trace 550e8400-e29b-41d4-a716-446655440000 start",
                    "trace 550e8400-e29b-41d4-a716-446655440001 start",
                ],
                "<uuid>",
                "446655440000",
            ),
        ]
    )
    def test_masking_collapses_variable_tokens(
        self, _name: str, lines: list[str], expected_token: str, raw_token: str
    ) -> None:
        patterns = mine_patterns([_sample(line) for line in lines])

        assert len(patterns) == 1
        assert patterns[0].count == 2
        assert expected_token in patterns[0].pattern
        assert raw_token not in patterns[0].pattern

    def test_error_count_includes_only_error_and_fatal(self) -> None:
        samples = [
            _sample("db connection dropped", severity="error"),
            _sample("db connection dropped", severity="fatal"),
            _sample("db connection dropped", severity="info"),
            _sample("db connection dropped", severity="warn"),
        ]

        patterns = mine_patterns(samples)

        assert len(patterns) == 1
        assert patterns[0].count == 4
        assert patterns[0].error_count == 2

    def test_orders_by_count_desc_with_volume_share(self) -> None:
        samples = [_sample("alpha event happened")] * 3 + [_sample("a totally separate message line")]

        patterns = mine_patterns(samples)

        assert [p.count for p in patterns] == [3, 1]
        assert patterns[0].volume_share_pct == 75.0
        assert patterns[1].volume_share_pct == 25.0

    def test_services_are_distinct_and_capped(self) -> None:
        samples = [_sample("same templated message", service=f"svc{i % 3}") for i in range(9)]

        patterns = mine_patterns(samples, max_services=2)

        assert patterns[0].count == 9
        assert patterns[0].services == ["svc0", "svc1"]

    def test_examples_are_distinct_and_capped(self) -> None:
        samples = [_sample(f"error code {i}") for i in range(5)]

        patterns = mine_patterns(samples, max_examples=2)

        # all five cluster together (the number is masked), but only two examples are kept
        assert patterns[0].count == 5
        assert [e.body for e in patterns[0].examples] == ["error code 0", "error code 1"]
        # examples carry the sampled row's metadata for display, not just the body
        assert patterns[0].examples[0].service_name == "api"
        assert patterns[0].examples[0].severity_text == "info"

    def test_long_bodies_are_truncated_before_mining(self) -> None:
        patterns = mine_patterns([_sample("x" * 1000)])

        assert len(patterns[0].examples[0].body) == 512

    def test_first_and_last_seen_span_the_cluster(self) -> None:
        earliest = dt.datetime(2026, 6, 23, 12, 0, 0, tzinfo=dt.UTC)
        middle = dt.datetime(2026, 6, 23, 12, 5, 0, tzinfo=dt.UTC)
        latest = dt.datetime(2026, 6, 23, 12, 10, 0, tzinfo=dt.UTC)
        samples = [
            _sample("steady message", ts=middle),
            _sample("steady message", ts=latest),
            _sample("steady message", ts=earliest),
        ]

        patterns = mine_patterns(samples)

        assert patterns[0].first_seen == earliest
        assert patterns[0].last_seen == latest

    def test_max_patterns_caps_returned_clusters(self) -> None:
        # distinct token-lengths force distinct clusters
        samples = [_sample(" ".join(["tok"] * n)) for n in range(1, 6)]

        patterns = mine_patterns(samples, max_patterns=2)

        assert len(patterns) == 2

    def test_empty_input_returns_empty(self) -> None:
        assert mine_patterns([]) == []
