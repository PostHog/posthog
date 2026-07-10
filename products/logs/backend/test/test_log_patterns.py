import re
import datetime as dt

from unittest import TestCase

from parameterized import parameterized

from products.logs.backend.log_patterns import (
    LogSample,
    _prepare_json_body,
    compile_match_regex,
    extract_match_literal,
    mine_patterns,
)


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


def _compile_prose(template: str, bodies: list[str], truncate: int = 512) -> str | None:
    # Prose logs: the prepared example and the raw line are the same text.
    samples = [_sample(b) for b in bodies]
    return compile_match_regex(template, samples, bodies, truncate=truncate)


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
        regex = _compile_prose(template, [raw_body.strip()])

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
        regex = _compile_prose(template, ["User dave not found"])

        assert regex is not None
        assert not re.search(regex, non_matching_body)

    def test_truncated_examples_drop_the_end_anchor(self) -> None:
        # A body that hit the mining truncation cap means the template only covers a prefix
        # of the raw line — the predicate must still match the full-length original.
        truncated_body = "prefix " + "x" * 505
        regex = _compile_prose("prefix <*>", [truncated_body])

        assert regex is not None
        assert re.search(regex, truncated_body + " continues beyond the cap")

    @parameterized.expand(
        [
            ("all_wildcards", "<*> <*> <*>"),
            ("literals_too_thin", "a <num> b"),
        ]
    )
    def test_templates_without_literal_content_get_no_regex(self, _name: str, template: str) -> None:
        assert _compile_prose(template, ["anything at all"]) is None

    def test_diverged_example_fails_validation(self) -> None:
        # Drain refines templates as rows merge, so a stored example can stop matching the
        # final template. Shipping that regex would filter to the wrong logs — it must be
        # withheld instead.
        assert _compile_prose("User <*> not found", ["User dave not found", "something entirely different"]) is None

    def test_no_examples_means_no_regex(self) -> None:
        assert compile_match_regex("User <*> not found", [], [], truncate=512) is None

    @parameterized.expand(
        [
            ("longest_run_wins", "at <uuid> failed to charge card for team <num>", "failed to charge card for team"),
            ("too_thin", "<*> ab <num>", None),
        ]
    )
    def test_extract_match_literal(self, _name: str, template: str, expected: str | None) -> None:
        assert (
            extract_match_literal(template, [template.replace("<uuid>", "x").replace("<num>", "1").replace("<*>", "y")])
            == expected
        )

    def test_extract_match_literal_withheld_when_absent_from_raw_lines(self) -> None:
        # The icontains filter runs against raw bodies; a literal that only exists in the
        # prepared form (here: whitespace-collapsed) would silently match nothing.
        assert extract_match_literal("job done ok", ["job   done\n\nok"]) is None
        assert extract_match_literal("Job Done OK", ["prefix job done ok suffix"]) == "Job Done OK"


class TestPrepareJsonBody(TestCase):
    @parameterized.expand(
        [
            ("message_key", '{"message": "User alice not found", "level": "error"}', "User alice not found"),
            ("msg_key", '{"msg": "connection reset", "attempt": 3}', "connection reset"),
            ("log_key", '{"log": "line from docker", "stream": "stdout"}', "line from docker"),
            ("event_key", '{"event": "payment failed", "order_id": 12}', "payment failed"),
            ("priority_order", '{"event": "second choice", "message": "first choice"}', "first choice"),
            ("not_json", "User alice not found", None),
            ("json_array", '[{"message": "in a list"}]', None),
            ("json_scalar_in_braces_invalid", "{not valid json}", None),
            ("empty_message_falls_to_shape", '{"message": "", "a": 1}', '{"a": <val> "message": <val>}'),
            ("non_string_message_falls_to_shape", '{"message": 42}', '{"message": <val>}'),
        ]
    )
    def test_json_body_reduction(self, _name: str, body: str, expected: str | None) -> None:
        assert _prepare_json_body(body) == expected

    def test_shape_is_key_order_and_value_invariant(self) -> None:
        # The two properties that stop shape-only JSON from fragmenting: same keys in any
        # order with any values must canonicalize identically.
        a = _prepare_json_body('{"user_id": 1, "action": "login", "ok": true}')
        b = _prepare_json_body('{"ok": false, "action": "logout", "user_id": 999}')
        assert a == b == '{"action": <val> "ok": <val> "user_id": <val>}'

    def test_nested_containers_keep_one_level_of_shape(self) -> None:
        assert (
            _prepare_json_body('{"ctx": {"b": 1, "a": 2}, "tags": [1, 2]}')
            == '{"ctx": {"a": <val> "b": <val>} "tags": [<val>]}'
        )


class TestJsonBodyMining(TestCase):
    def test_json_bodies_cluster_by_message_and_regex_matches_the_raw_line(self) -> None:
        # The end-to-end contract for structured logs: mining sees the extracted message (one
        # template instead of punctuation fragments), while the shipped predicate still matches
        # the raw JSON rows in ClickHouse — which requires the unanchored compile variant, since
        # the message is a substring of the raw line.
        raws = [
            f'{{"level": "error", "message": "User {name} not found", "request_id": {i}}}'
            for i, name in enumerate(("alice", "bob", "carol"))
        ]
        patterns = mine_patterns([_sample(raw) for raw in raws])

        assert len(patterns) == 1
        assert patterns[0].pattern == "User <*> not found"
        assert patterns[0].match_regex is not None
        compiled = re.compile(patterns[0].match_regex)
        for raw in raws:
            assert compiled.search(raw)
        assert patterns[0].match_literal == "not found"

    def test_shape_only_json_clusters_once_and_withholds_predicates(self) -> None:
        # No message field: identical shapes must become one stable template (Loki drops these
        # lines entirely; we template the shape instead), but neither predicate can honestly
        # match the raw rows — "<val>" never appears in them — so both must be withheld.
        raws = ['{"user_id": 1, "ok": true}', '{"ok": false, "user_id": 22}', '{"user_id": 333, "ok": true}']
        patterns = mine_patterns([_sample(raw) for raw in raws])

        assert len(patterns) == 1
        assert patterns[0].match_regex is None
        assert patterns[0].match_literal is None

    def test_message_with_json_escaped_content_withholds_the_regex(self) -> None:
        # The raw row stores the newline as a two-character escape (\n); the extracted message
        # has a real newline. A predicate validated only against the prepared form would ship
        # and silently match nothing — raw validation must withhold it.
        raw = '{"message": "first line\\nsecond line of failure"}'
        patterns = mine_patterns([_sample(raw)])

        assert patterns[0].match_regex is None

    def test_prose_bodies_are_untouched_by_json_handling(self) -> None:
        patterns = mine_patterns([_sample("User alice not found"), _sample("User bob not found")])

        assert patterns[0].pattern == "User <*> not found"
        assert patterns[0].match_regex is not None
        assert re.match(patterns[0].match_regex, "User carol not found")
