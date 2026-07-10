import re
import datetime as dt

from unittest import TestCase

from parameterized import parameterized

from products.logs.backend.log_patterns import LogSample, compile_match_regex, extract_match_literal, mine_patterns


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

    def test_mined_patterns_carry_a_regex_that_matches_their_own_examples(self) -> None:
        # End-to-end self-consistency: whatever mining produced, the compiled predicate must
        # match the rows it came from — the invariant the whole "view matching logs" flow
        # rests on.
        samples = [_sample(f"User {name} not found in {i} ms") for i, name in enumerate(("alice", "bob", "carol"))]

        patterns = mine_patterns(samples)

        assert patterns[0].match_regex is not None
        compiled = re.compile(patterns[0].match_regex)
        for example in patterns[0].examples:
            assert compiled.search(example.body)


class TestCompileMatchRegex(TestCase):
    @parameterized.expand(
        [
            # template, raw body that must match (arbitrary whitespace runs, live values)
            ("User <*> not found", "User dave not found"),
            ("User <*> not found", "  User   dave\tnot   found  "),
            ("took <num> ms", "took 12345 ms"),
            ("request <uuid> failed", "request 93fce79d-6926-4b08-8fa5-00ffd8e65f4e failed"),
            ("peer <ip> disconnected", "peer 10.32.243.94 disconnected"),
            ("token <hex> rejected", "token 0xdeadbeef rejected"),
            ("path /api/v1/users?id=<num> hit", "path /api/v1/users?id=42 hit"),
        ]
    )
    def test_compiled_regex_matches_raw_bodies(self, template: str, raw_body: str) -> None:
        regex = compile_match_regex(template, [_sample(raw_body.strip())], truncate=512)

        assert regex is not None
        assert re.search(regex, raw_body)

    @parameterized.expand(
        [
            # anchoring: a filter that matches unrelated lines is the failure mode this guards
            ("User <*> not found", "prefix junk User dave not found"),
            ("User <*> not found", "User dave not found trailing junk"),
        ]
    )
    def test_compiled_regex_is_anchored(self, template: str, non_matching_body: str) -> None:
        regex = compile_match_regex(template, [_sample("User dave not found")], truncate=512)

        assert regex is not None
        assert not re.search(regex, non_matching_body)

    def test_truncated_examples_drop_the_end_anchor(self) -> None:
        # A body that hit the mining truncation cap means the template only covers a prefix
        # of the raw line — the predicate must still match the full-length original.
        truncated_body = "prefix " + "x" * 505
        regex = compile_match_regex("prefix <*>", [_sample(truncated_body)], truncate=512)

        assert regex is not None
        assert re.search(regex, truncated_body + " continues beyond the cap")

    @parameterized.expand(
        [
            ("all_wildcards", "<*> <*> <*>"),
            ("literals_too_thin", "a <num> b"),
        ]
    )
    def test_templates_without_literal_content_get_no_regex(self, _name: str, template: str) -> None:
        assert compile_match_regex(template, [_sample("anything at all")], truncate=512) is None

    def test_diverged_example_fails_validation(self) -> None:
        # Drain refines templates as rows merge, so a stored example can stop matching the
        # final template. Shipping that regex would filter to the wrong logs — it must be
        # withheld instead.
        examples = [_sample("User dave not found"), _sample("something entirely different")]

        assert compile_match_regex("User <*> not found", examples, truncate=512) is None

    def test_no_examples_means_no_regex(self) -> None:
        assert compile_match_regex("User <*> not found", [], truncate=512) is None

    @parameterized.expand(
        [
            ("longest_run_wins", "at <uuid> failed to charge card for team <num>", "failed to charge card for team"),
            ("too_thin", "<*> ab <num>", None),
        ]
    )
    def test_extract_match_literal(self, _name: str, template: str, expected: str | None) -> None:
        assert extract_match_literal(template) == expected
