import re
import datetime as dt
from itertools import zip_longest

from unittest import TestCase

from hypothesis import (
    assume,
    given,
    settings,
    strategies as st,
)
from parameterized import parameterized

from products.logs.backend.log_patterns import (
    _HOST_SUFFIXES,
    _MASKING_INSTRUCTIONS,
    _PLACEHOLDER_PATTERNS,
    _WHITESPACE_RE,
    LogSample,
    _prepare_body,
    _prepare_json_body,
    compile_match_regex,
    extract_match_literal,
    mine_patterns,
    pattern_fingerprint,
)

_BODY_TRUNCATE = 512

# Printable, non-whitespace characters: Drain splits on whitespace, so these are the
# characters a single token can hold. The range covers regex metacharacters and the angle
# brackets the placeholders use, which is where escaping and placeholder round-tripping break.
_token_st = st.text(st.characters(min_codepoint=33, max_codepoint=126), min_size=1, max_size=20)
_gap_st = st.sampled_from([" ", "  ", "\t", "\n", "\r\n", " \n  "])


@st.composite
def _log_body_st(draw: st.DrawFn) -> str:
    tokens = draw(st.lists(_token_st, min_size=1, max_size=150))
    body = tokens[0]
    for token in tokens[1:]:
        body += draw(_gap_st) + token
    return body


_log_word_st = st.sampled_from(
    ["request", "failed", "retrying", "user", "team", "cache", "hit", "GET", "POST", "attempt", "closed"]
)
_key_st = st.sampled_from(["team_id=", "attempt=", "status=", "peer=", "ts=", "job="])
# Values that masking is meant to consume. Drawing these rather than random characters is
# what makes the placeholder round-trip reachable: a mask that never fires proves nothing.
_maskable_st = st.one_of(
    st.integers(min_value=0, max_value=10**12).map(str),
    st.tuples(*[st.integers(min_value=0, max_value=255)] * 4).map(lambda octets: ".".join(map(str, octets))),
    st.uuids().map(str),
    st.datetimes(min_value=dt.datetime(2020, 1, 1), max_value=dt.datetime(2030, 1, 1)).map(dt.datetime.isoformat),
    st.text("0123456789abcdef", min_size=16, max_size=40),
    st.integers(min_value=0, max_value=999).map(lambda n: f"0x{n:x}"),
    st.tuples(st.integers(min_value=0, max_value=99), st.integers(min_value=0, max_value=99)).map(
        lambda parts: f"{parts[0]}.{parts[1]}"
    ),
)


@st.composite
def _log_line_st(draw: st.DrawFn) -> str:
    parts = draw(
        st.lists(
            st.one_of(_log_word_st, _maskable_st, st.tuples(_key_st, _maskable_st).map("".join)),
            min_size=1,
            max_size=14,
        )
    )
    return " ".join(parts)


# Always crosses the truncation cap. Hypothesis biases toward small inputs, so a general body
# strategy almost never reaches the cap and leaves the prefix handling untested.
@st.composite
def _long_log_body_st(draw: st.DrawFn) -> str:
    prefix = draw(st.lists(_token_st, min_size=1, max_size=8))
    filler = draw(st.text(st.characters(min_codepoint=33, max_codepoint=126), min_size=3, max_size=14))
    gap = draw(_gap_st)
    repeats = _BODY_TRUNCATE // (len(filler) + len(gap)) + draw(st.integers(min_value=2, max_value=20))
    return gap.join([*prefix, *[filler] * repeats])


def _sample(
    body: str,
    severity: str = "info",
    service: str = "api",
    ts: dt.datetime | None = None,
    truncated: bool = False,
) -> LogSample:
    return LogSample(
        body=body,
        severity_text=severity,
        service_name=service,
        timestamp=ts or dt.datetime(2026, 6, 23, 12, 0, 0, tzinfo=dt.UTC),
        truncated=truncated,
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
            # the version guard keys on the character before the address, so a URL host,
            # which is the one place an address does follow a "/", must still mask
            (
                "ipv4_in_url",
                ["fetched http://10.0.0.1/health ok", "fetched http://192.168.1.1/health ok"],
                "<ip>",
                "10.0.0.1",
            ),
            # only a "." that carries on a dotted run rules the address out, so an address
            # that ends a sentence still masks
            (
                "ipv4_at_end_of_sentence",
                ["closed connection to 10.0.0.1.", "closed connection to 192.168.1.1."],
                "<ip>",
                "10.0.0.1",
            ),
            (
                "uuid",
                [
                    "trace 550e8400-e29b-41d4-a716-446655440000 start",
                    "trace 550e8400-e29b-41d4-a716-446655440001 start",
                ],
                "<uuid>",
                "446655440000",
            ),
            (
                "timestamp_iso_t",
                [
                    "job 2026-08-12T08:10:43.397557Z retried",
                    "job 2026-08-13T09:11:44.123456Z retried",
                ],
                "<timestamp>",
                "397557Z",
            ),
            (
                "timestamp_space_separated",
                [
                    "job 2026-08-12 08:10:43.397557 retried",
                    "job 2026-08-13 09:11:44.123456 retried",
                ],
                "<timestamp>",
                "397557",
            ),
            (
                "version_after_product",
                ["agent Chrome/139.0.0.0 connected", "agent Chrome/140.0.7.1 connected"],
                "<version>",
                "139",
            ),
            (
                "protocol_version",
                ["served HTTP/1.1 request", "served HTTP/2.0 request"],
                "<version>",
                "1.1",
            ),
            (
                "timestamp_utc_offset",
                [
                    "job 2026-08-12T08:10:43+00:00 retried",
                    "job 2026-08-13T09:11:44+02:00 retried",
                ],
                "<timestamp>",
                "12T08",
            ),
            (
                "hostname",
                ["upstream ingest.example.com refused", "upstream ingest.example.net refused"],
                "<host>",
                "example",
            ),
            (
                "subdomains",
                ["proxied to eu.i.example.com ok", "proxied to us.i.example.com ok"],
                "<host>",
                "example",
            ),
            (
                "timestamp_klog",
                [
                    "I0812 15:41:23.951822 12 proxier.go:99] synced",
                    "I0813 16:02:11.112233 12 proxier.go:99] synced",
                ],
                "<klogtime>",
                "0812",
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

    @parameterized.expand(
        [
            ("chrome_version", "agent Chrome/139.0.0.0 connected"),
            ("four_part_release", "rolled out build/2.14.0.3 to canary"),
            ("longer_dotted_run", "schema version 1.2.3.4.5 loaded"),
        ]
    )
    def test_version_strings_are_not_masked_as_ips(self, _name: str, line: str) -> None:
        # A dotted quad in a version is indistinguishable from an address by octet range, so
        # the mask keys on the surrounding characters. Reading "Chrome/<ip>" in a template
        # sends the reader looking for a network problem that is not there.
        patterns = mine_patterns([_sample(line)])

        assert "<ip>" not in patterns[0].pattern

    @parameterized.expand(
        [
            ("decimal_metric", "request took duration=1.5 seconds"),
            ("numeric_path_segment", "POST /api/projects/2/query/ returned 200"),
            ("module_version", "loaded python3.13 runtime"),
        ]
    )
    def test_plain_decimals_are_not_masked_as_versions(self, _name: str, line: str) -> None:
        # The "/" requirement is what separates a version from a measurement. Masking a
        # latency or a ratio as <version> hides the number a reader came for.
        patterns = mine_patterns([_sample(line)])

        assert "<version>" not in patterns[0].pattern

    @parameterized.expand(
        [
            ("module_path", "handler resolved in products.logs.backend module"),
            ("logger_name", "logger django_structlog.celery.receivers ready"),
            ("source_file", "raised from MergeFromLogEntryTask.cpp while merging"),
        ]
    )
    def test_dotted_code_paths_are_not_masked_as_hosts(self, _name: str, line: str) -> None:
        # A hostname mask keyed on "any trailing alphabetic label" swallows module paths,
        # logger names, and source files, which is the literal content the template is for.
        patterns = mine_patterns([_sample(line)])

        assert "<host>" not in patterns[0].pattern

    def test_a_name_that_starts_with_an_address_masks_the_address_first(self) -> None:
        # Wildcard-DNS names carry an address in their leading labels ("10.0.0.1.nip.io"), and
        # ip runs before host by design, so the address masks and the domain masks after it.
        # Both halves are variable and both are covered; the order is what this pins, because
        # letting host win would bury the address a reader opened the pattern for.
        patterns = mine_patterns([_sample("upstream 10.0.0.1.nip.io refused")])

        assert patterns[0].pattern == "upstream <ip>.<host> refused"

    def test_a_dotted_run_longer_than_any_hostname_keeps_its_head_literal(self) -> None:
        # The label repeat is capped because an uncapped one retries the suffix alternation at
        # every boundary of a long dotted run, at a cost that grows with the square of its
        # length. Masking only the tail is the visible price of that cap, so a crafted run of
        # single-character labels must leave its head in the template.
        patterns = mine_patterns([_sample("upstream " + "a." * 40 + "example.com refused")])

        assert "<host>" in patterns[0].pattern
        assert "a.a.a." in patterns[0].pattern

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
        # one token with no space inside the cap: there is no boundary to cut back to
        patterns = mine_patterns([_sample("x" * 1000)])

        assert len(patterns[0].examples[0].body) == 512

    def test_truncation_cuts_back_to_a_word_boundary(self) -> None:
        # A hard character cut leaves a partial token, which Drain treats as a literal. Bodies
        # that differ only past the cap then fragment into one cluster per cut point instead
        # of merging, and the partial word shows up in the template a person reads.
        body = "prefix " + " ".join(["Macintosh"] * 200)

        patterns = mine_patterns([_sample(body)])

        example = patterns[0].examples[0]
        assert len(example.body) <= 512
        assert set(example.body.split(" ")) == {"prefix", "Macintosh"}

    def test_regex_matches_a_long_body_whose_truncated_example_was_dropped(self) -> None:
        # Truncation is a property of the cluster, not of the examples that survive into it.
        # The dedup check compares text only, so a long body that prepares to the same text
        # as a short one leaves no truncated example behind. Deriving the end anchor from the
        # retained examples then builds a filter that excludes the long line it was mined
        # from. The example cap drops a truncated example the same way.
        short = " ".join(f"tok{i}" for i in range(80))
        long_body = f"{short} {'X' * 60}"
        assert len(short) < 512 < len(long_body)

        patterns = mine_patterns([_sample(short), _sample(long_body)])

        assert len(patterns) == 1
        assert patterns[0].match_regex is not None
        assert re.search(patterns[0].match_regex, long_body)

    def test_word_boundary_truncation_still_drops_the_end_anchor(self) -> None:
        # Cutting back to a boundary puts the prepared body under the cap, so a length check
        # can no longer tell truncation apart from a short line. Getting that wrong anchors
        # the predicate at the end, and it matches none of the real, longer lines.
        body = "prefix " + " ".join(["Macintosh"] * 200)

        patterns = mine_patterns([_sample(body)])

        assert patterns[0].match_regex is not None
        assert re.search(patterns[0].match_regex, body)

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
        # match the RAW rows it came from — raw lines are what the predicate executes against
        # in ClickHouse, and a regex that only matches prepared bodies is exactly the broken
        # predicate this invariant exists to prevent.
        bodies = [f"User {name} not found in {i} ms" for i, name in enumerate(("alice", "bob", "carol"))]

        patterns = mine_patterns([_sample(body) for body in bodies])

        assert patterns[0].match_regex is not None
        compiled = re.compile(patterns[0].match_regex)
        for body in bodies:
            assert compiled.search(body)

    @parameterized.expand(
        [
            (
                "iso",
                "2026-08-12T08:10:43.397557Z task_retrying attempt=3",
                "2026-08-19T09:04:17.112233Z task_retrying attempt=7",
            ),
            (
                "klog",
                "I0812 08:10:43.397557 12 worker.go:31] task_retrying",
                "I0819 09:04:17.112233 12 worker.go:31] task_retrying",
            ),
        ]
    )
    def test_same_statement_on_different_dates_shares_fingerprint(
        self, _name: str, monday_body: str, week_later_body: str
    ) -> None:
        # The patterns diff compares fingerprints across two windows (default: one week
        # apart). A timestamp fragment surviving masking becomes a literal run, so the
        # same log statement would fingerprint differently and show up as a false
        # new/gone pair.
        monday = mine_patterns([_sample(monday_body)])
        week_later = mine_patterns([_sample(week_later_body)])

        assert pattern_fingerprint(monday[0].pattern) == pattern_fingerprint(week_later[0].pattern)

    def test_match_regex_matches_siblings_with_different_timestamps(self) -> None:
        # An unmasked timestamp baked into match_regex narrows the "view matching logs"
        # pivot to the single line the pattern was mined from.
        patterns = mine_patterns([_sample("task_retrying at 2026-08-12T08:10:43.397557Z scheduled")])

        assert patterns[0].match_regex is not None
        assert re.search(patterns[0].match_regex, "task_retrying at 2026-08-19T14:02:11.000001Z scheduled")


def _compile_prose(template: str, bodies: list[str], truncated: bool = False) -> str | None:
    # Prose logs: the prepared example and the raw line are the same text.
    samples = [_sample(b, truncated=truncated) for b in bodies]
    return compile_match_regex(template, samples, bodies, truncated=truncated)


class TestCompileMatchRegex(TestCase):
    @parameterized.expand(
        [
            # template, raw body that must match (arbitrary whitespace runs, live values)
            ("User <*> not found", "User dave not found"),
            ("User <*> not found", "  User   dave\tnot   found  "),
            ("took <num> ms", "took 12345 ms"),
            ("request <uuid> failed", "request 93fce79d-6926-4b08-8fa5-00ffd8e65f4e failed"),
            ("peer <ip> disconnected", "peer 10.32.243.94 disconnected"),
            ("upstream <host> refused", "upstream eu.i.example.com refused"),
            ("token <hex> rejected", "token 0xdeadbeef rejected"),
            ("agent Chrome/<version> connected", "agent Chrome/139.0.0.0 connected"),
            ("path /api/v1/users?id=<num> hit", "path /api/v1/users?id=42 hit"),
            ("job <timestamp> finished", "job 2026-08-12T08:10:43.397557Z finished"),
            ("I<klogtime> synced iptables", "I0812 15:41:23.951822 synced iptables"),
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
        regex = _compile_prose("prefix <*>", [truncated_body], truncated=True)

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

    def test_prose_pattern_never_falls_back_to_an_unanchored_regex(self) -> None:
        # The unanchored fallback exists solely for JSON-extracted messages (substrings of
        # their raw rows). A prose raw line with surrounding context (e.g. a shipper-prepended
        # syslog prefix) fails the anchored form and must be withheld — falling back would ship
        # a predicate matching mid-line occurrences the anchoring guarantee exists to exclude.
        raws = ["User dave not found", "<13>Jan 1 host app: User bob not found"]
        assert _compile_prose("User <*> not found", raws) is None

    def test_no_examples_means_no_regex(self) -> None:
        assert compile_match_regex("User <*> not found", [], []) is None

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
            ("leading_whitespace_and_bom", ' ﻿ {"message": "still json"}', "still json"),
            ("msg_key", '{"msg": "connection reset", "attempt": 3}', "connection reset"),
            ("log_key", '{"log": "line from docker", "stream": "stdout"}', "line from docker"),
            ("event_key", '{"event": "payment failed", "order_id": 12}', "payment failed"),
            ("priority_order", '{"event": "second choice", "message": "first choice"}', "first choice"),
            ("not_json", "User alice not found", None),
            ("json_array", '[{"message": "in a list"}]', None),
            ("json_scalar_in_braces_invalid", "{not valid json}", None),
            ("empty_message_is_not_a_message", '{"message": "", "a": 1}', None),
            ("non_string_message_is_not_a_message", '{"message": 42}', None),
            ("no_message_key", '{"user_id": 1, "ok": true}', None),
            # A producer controls the body, and an integer past sys.get_int_max_str_digits()
            # raises a bare ValueError from the number parser rather than a JSONDecodeError.
            ("integer_past_the_digit_limit", '{"message": "hi", "n": ' + "9" * 5000 + "}", None),
        ]
    )
    def test_json_body_reduction(self, _name: str, body: str, expected: str | None) -> None:
        assert _prepare_json_body(body) == expected


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

    def test_a_cluster_mixing_json_and_prose_rows_withholds_the_unanchored_regex(self) -> None:
        # The unanchored form is only honest when every raw row is JSON, where the template is a
        # substring by construction. One JSON row among prose rows would otherwise buy the whole
        # cluster a regex matching a prose line wherever the text appears, not where it starts.
        rows = [_sample(f'{{"message": "cache miss for key {i}"}}') for i in range(5)]
        rows += [_sample(f"cache miss for key {i}") for i in range(5, 10)]

        patterns = mine_patterns(rows)

        assert len(patterns) == 1
        assert patterns[0].match_regex is None

    def test_message_less_json_keeps_a_predicate_that_matches_the_raw_row(self) -> None:
        # Rewriting these bodies into a canonical shape collapses them into one template, but
        # that template then describes text absent from the raw row, so every predicate has to
        # be withheld and the pattern loses the drill-down to its logs. Mining the body
        # unchanged is what keeps the pivot working.
        raws = ['{"user_id": 1, "ok": true}', '{"user_id": 22, "ok": true}', '{"user_id": 333, "ok": true}']
        patterns = mine_patterns([_sample(raw) for raw in raws])

        assert len(patterns) == 1
        assert patterns[0].match_regex is not None
        compiled = re.compile(patterns[0].match_regex)
        for raw in raws:
            assert compiled.search(raw)

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


_uuid_st = st.tuples(st.uuids(), st.booleans()).map(lambda t: str(t[0]).upper() if t[1] else str(t[0]))
_hex_0x_st = st.text("0123456789abcdefABCDEF", min_size=1, max_size=32).map(lambda s: f"0x{s}")
_hex_bare_st = st.text("0123456789abcdefABCDEF", min_size=16, max_size=40)
_num_st = st.integers(min_value=0, max_value=10**12).map(str)
_word_st = st.text("abcdefghijklmnopqrstuvwxyz", min_size=3, max_size=10)


@st.composite
def _timestamp_st(draw: st.DrawFn) -> str:
    instant = draw(st.datetimes(min_value=dt.datetime(1000, 1, 1), max_value=dt.datetime(9999, 12, 31, 23, 59, 59)))
    separator = draw(st.sampled_from(["T", " "]))
    text = instant.strftime(f"%Y-%m-%d{separator}%H:%M:%S")
    fraction = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=999_999_999)))
    if fraction is not None:
        text += f"{draw(st.sampled_from(['.', ',']))}{fraction}"
    return text + draw(st.sampled_from(["", "Z", "+00:00", "-05:30", "+0230", "-1145"]))


_ipv4_st = st.tuples(*[st.integers(min_value=0, max_value=255)] * 4).map(lambda octets: ".".join(map(str, octets)))
# Characters an address really follows in a log body. "/" is deliberately absent: that is
# the one the guard rejects, and the URL case below covers "//" separately.
_delimiter_st = st.sampled_from([" ", "=", ":", '"', ",", "[", "(", "|"])
_product_st = st.text("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=1, max_size=14)
_scheme_st = st.sampled_from(["http", "https"])


# Up to six parts, past the four a browser build uses: a bounded mask consumes the first four
# of a longer release and leaves the rest as <num>, which is a template of its own again.
_version_st = st.lists(st.integers(min_value=0, max_value=9999), min_size=2, max_size=6).map(
    lambda parts: ".".join(map(str, parts))
)
_decimal_context_st = st.sampled_from(["duration_ms=", "ratio=", "load ", "p95="])
_label_st = st.text("abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=12)
# A label that is itself a host suffix would make a "code path" strategy generate a real
# hostname, so it is excluded from both strategies below.
_non_suffix_label_st = _label_st.filter(lambda label: label not in _HOST_SUFFIXES)


# A name whose first four labels are a dotted quad ("0.0.0.0.ai", "10.0.0.1.nip.io") is an
# address with a domain after it, and ip runs before host by design, so it masks as "<ip>.<host>"
# rather than a single placeholder. That precedence has its own case above; excluding the shape
# here keeps this strategy to names the host mask alone owns.
# The trailing guards mirror the ip mask's own: a fifth label that starts with a digit makes the
# leading quad the head of a longer dotted run, which the mask leaves alone.
_LEADING_ADDRESS_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?!\d)(?!\.\d)")


# Up to five labels before the suffix, past the deepest names that show up in real logs
# ("pod.ns.svc.cluster.local", "a.b.c.example.co.uk"). The mask caps how many labels it will
# consume, and this range is deliberately not derived from that cap: tightening the cap below
# what real hostnames need has to fail the collapse property, not narrow the strategy with it.
@st.composite
def _fqdn_st(draw: st.DrawFn) -> str:
    labels = draw(st.lists(_non_suffix_label_st, min_size=1, max_size=5))
    name = ".".join([*labels, draw(st.sampled_from(_HOST_SUFFIXES))])
    assume(not _LEADING_ADDRESS_RE.match(name))
    return name


@st.composite
def _dotted_code_path_st(draw: st.DrawFn) -> str:
    return ".".join(draw(st.lists(_non_suffix_label_st, min_size=2, max_size=4)))


_slash_version_st = st.tuples(_product_st, _version_st).map(lambda t: f"{t[0]}/{t[1]}")
_variable_token_st = st.one_of(
    _uuid_st, _hex_0x_st, _hex_bare_st, _num_st, _timestamp_st(), _ipv4_st, _slash_version_st, _fqdn_st()
)


class TestMaskingProperties(TestCase):
    def test_every_mask_name_has_a_registered_placeholder(self) -> None:
        # A masking rule without a placeholder entry produces templates whose match_regex
        # can never validate, silently degrading the "view matching logs" pivot.
        for instruction in _MASKING_INSTRUCTIONS:
            assert f"<{instruction.mask_with}>" in _PLACEHOLDER_PATTERNS

    @given(value=_uuid_st)
    @settings(deadline=None)
    def test_any_uuid_masks_to_placeholder(self, value: str) -> None:
        patterns = mine_patterns([_sample(f"trace {value} start")])

        assert patterns[0].pattern == "trace <uuid> start"

    @given(value=st.one_of(_hex_0x_st, _hex_bare_st))
    @settings(deadline=None)
    def test_any_hex_token_masks_to_placeholder(self, value: str) -> None:
        patterns = mine_patterns([_sample(f"token {value} rejected")])

        assert patterns[0].pattern == "token <hex> rejected"

    @given(value=_num_st)
    @settings(deadline=None)
    def test_any_integer_token_masks_to_num(self, value: str) -> None:
        patterns = mine_patterns([_sample(f"took {value} ms")])

        assert patterns[0].pattern == "took <num> ms"

    @given(value=_timestamp_st())
    @settings(deadline=None)
    def test_any_iso_timestamp_masks_to_placeholder(self, value: str) -> None:
        patterns = mine_patterns([_sample(f"job {value} done")])

        assert patterns[0].pattern == "job <timestamp> done"

    @given(first_instant=_timestamp_st(), second_instant=_timestamp_st())
    @settings(deadline=None)
    def test_same_statement_at_two_instants_shares_fingerprint(self, first_instant: str, second_instant: str) -> None:
        first = mine_patterns([_sample(f"{first_instant} task_retrying attempt=3")])
        second = mine_patterns([_sample(f"{second_instant} task_retrying attempt=7")])

        assert pattern_fingerprint(first[0].pattern) == pattern_fingerprint(second[0].pattern)

    @given(
        words=st.lists(_word_st, min_size=1, max_size=6),
        values=st.lists(_variable_token_st, min_size=1, max_size=4),
    )
    @settings(deadline=None)
    def test_match_regex_round_trips_any_masked_body(self, words: list[str], values: list[str]) -> None:
        # compile_match_regex validates against the sampled body, so a placeholder pattern
        # that matches less than its masking rule consumed surfaces here as a None regex.
        interleaved = [token for pair in zip_longest(words, values) for token in pair if token is not None]
        body = f"event {' '.join(interleaved)} done"
        patterns = mine_patterns([_sample(body)])

        assert len(patterns) == 1
        assert patterns[0].match_regex is not None
        assert re.search(patterns[0].match_regex, body)


_letter_st = st.text("ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=1, max_size=2)
_digit_letter_run_st = st.tuples(st.integers(0, 99), _letter_st, st.integers(0, 999999)).map(
    lambda t: f"{t[0]}{t[1]}{t[2]}"
)
_date_only_st = st.dates(min_value=dt.date(1000, 1, 1)).map(str)
_minute_timestamp_st = st.datetimes(min_value=dt.datetime(1000, 1, 1)).map(
    lambda instant: instant.strftime("%Y-%m-%dT%H:%M")
)
_letter_hex_st = st.text("abcdef", min_size=4, max_size=12)
_truncated_uuid_st = st.uuids().map(lambda u: str(u)[:23])

# Tokens the masker deliberately leaves (fully or partly) literal. A pivot regex mined
# from a masked body must not match a sibling holding one of these in the same slot.
_five_octet_st = st.tuples(*[st.integers(min_value=0, max_value=255)] * 5).map(
    lambda octets: ".".join(map(str, octets))
)
_versioned_quad_st = st.tuples(_product_st, _ipv4_st).map(lambda t: f"{t[0]}/{t[1]}")
_plain_decimal_st = st.tuples(st.integers(min_value=0, max_value=9999), st.integers(min_value=0, max_value=999)).map(
    lambda t: f"{t[0]}.{t[1]}"
)


@st.composite
def _bare_klog_st(draw: st.DrawFn) -> str:
    # A klog date-time with no severity letter in front. The klog mask requires that
    # letter, so this stays literal and must not be pulled into an ISO timestamp pivot.
    return draw(_klog_header_st())[1:]


# One row per (masked kind, confusable neighbor). Both halves of the row matter: the mask
# has to tell the pair apart, and so does the pivot regex the mask produces. A single
# union-of-everything property dilutes each pair to a fraction of the example budget, so
# every pair draws its own.
_CONFUSABLE_PAIRS = [
    ("num_vs_digit_letter_run", _num_st, _digit_letter_run_st),
    ("timestamp_vs_digit_letter_run", _timestamp_st(), _digit_letter_run_st),
    ("timestamp_vs_date_only", _timestamp_st(), _date_only_st),
    ("timestamp_vs_minute_precision", _timestamp_st(), _minute_timestamp_st),
    ("uuid_vs_truncated_uuid", _uuid_st, _truncated_uuid_st),
    ("hex_vs_letter_only_hex", st.one_of(_hex_0x_st, _hex_bare_st), _letter_hex_st),
    ("ip_vs_five_octets", _ipv4_st, _five_octet_st),
    ("ip_vs_versioned_quad", _ipv4_st, _versioned_quad_st),
    ("version_vs_plain_decimal", _slash_version_st, _plain_decimal_st),
    ("host_vs_dotted_code_path", _fqdn_st(), _dotted_code_path_st()),
    ("timestamp_vs_bare_klog_form", _timestamp_st(), _bare_klog_st()),
]


class TestPivotSoundness(TestCase):
    @parameterized.expand([(name,) for name, _, _ in _CONFUSABLE_PAIRS])
    @given(data=st.data())
    @settings(deadline=None)
    def test_confusable_neighbor_stays_distinguishable(self, name: str, data: st.DataObject) -> None:
        value_st, impostor_st = next((v, i) for n, v, i in _CONFUSABLE_PAIRS if n == name)
        value_body = f"event {data.draw(value_st)} done"
        impostor_body = f"event {data.draw(impostor_st)} done"

        mined = mine_patterns([_sample(value_body)])[0]
        impostor_template = mine_patterns([_sample(impostor_body)])[0].pattern

        # A masking rule that also swallows its neighbor erases the literal content the
        # template exists to show. Asserted first, and unconditionally: guarding the pivot
        # check on "the templates differ" makes an over-broad mask pass by doing nothing.
        assert impostor_template != mined.pattern
        # A placeholder broader than the rule that produced it pulls unrelated lines into
        # the "view matching logs" pivot.
        assert mined.match_regex is not None
        assert not re.search(mined.match_regex, impostor_body)


class TestIpMaskProperties(TestCase):
    """The cases above pin specific addresses; these hold the guard over every octet value.

    The guard reads the characters around the address, so the property that matters is which
    contexts still mask and which no longer do, across the whole address space.
    """

    @given(address=_ipv4_st, delimiter=_delimiter_st)
    @settings(max_examples=400, deadline=None)
    def test_any_address_after_a_plain_delimiter_masks(self, address: str, delimiter: str) -> None:
        patterns = mine_patterns([_sample(f"peer{delimiter}{address} closed")])

        assert "<ip>" in patterns[0].pattern
        assert address not in patterns[0].pattern

    @given(address=_ipv4_st, product=_product_st)
    @settings(max_examples=400, deadline=None)
    def test_no_address_is_read_out_of_a_version_after_a_product_name(self, address: str, product: str) -> None:
        # Every dotted quad is a valid version string too, so this has to hold for all of
        # them, not only for the browser builds the example cases use.
        patterns = mine_patterns([_sample(f"agent {product}/{address} connected")])

        assert "<ip>" not in patterns[0].pattern

    @given(address=_ipv4_st)
    @settings(max_examples=400, deadline=None)
    def test_any_address_that_ends_a_sentence_masks(self, address: str) -> None:
        # The trailing guard exists to keep the mask off a longer dotted run, so it has to
        # let a "." that ends the line through, whatever the last octet is.
        patterns = mine_patterns([_sample(f"closed connection to {address}.")])

        assert "<ip>" in patterns[0].pattern
        assert address not in patterns[0].pattern

    @given(run=_five_octet_st)
    @settings(max_examples=400, deadline=None)
    def test_no_address_is_read_out_of_a_longer_dotted_run(self, run: str) -> None:
        # The trailing guard turns on whether the next "." carries on the run, so the octet
        # values are what decide it, and neither the head nor the tail of the run may mask.
        patterns = mine_patterns([_sample(f"schema version {run} loaded")])

        assert "<ip>" not in patterns[0].pattern

    @given(address=_ipv4_st, scheme=_scheme_st)
    @settings(max_examples=400, deadline=None)
    def test_any_address_in_a_url_still_masks(self, address: str, scheme: str) -> None:
        # A URL host is the one place an address does follow a "/". An earlier version of the
        # guard blocked every "/" and silently stopped masking these.
        patterns = mine_patterns([_sample(f"GET {scheme}://{address}/health ok")])

        assert "<ip>" in patterns[0].pattern
        assert address not in patterns[0].pattern


class TestVersionMaskProperties(TestCase):
    """The cases above pin browser and protocol versions; these hold the rule over all parts.

    The mask trades on one character. Everything after a slash is a version, everything else
    keeps its number, so both properties test that line rather than a handful of versions.
    """

    @given(product=_product_st, version=_version_st)
    @settings(max_examples=400, deadline=None)
    def test_any_version_after_a_product_name_collapses_to_one_placeholder(self, product: str, version: str) -> None:
        patterns = mine_patterns([_sample(f"agent {product}/{version} connected")])

        # exact template: however many parts, one placeholder, not one <num> per part
        assert patterns[0].pattern == f"agent {product}/<version> connected"

    @given(context=_decimal_context_st, whole=st.integers(min_value=0, max_value=9999), frac=st.integers(0, 999))
    @settings(max_examples=400, deadline=None)
    def test_decimals_outside_a_path_keep_their_number(self, context: str, whole: int, frac: int) -> None:
        # Latencies, ratios, and load averages are decimals too. Reading one as a version
        # would hide the measurement the person opened the pattern for.
        patterns = mine_patterns([_sample(f"request {context}{whole}.{frac} done")])

        assert "<version>" not in patterns[0].pattern

    @given(product=_product_st, version_a=_version_st, version_b=_version_st)
    @settings(max_examples=300, deadline=None)
    def test_lines_differing_only_by_version_share_a_fingerprint(
        self, product: str, version_a: str, version_b: str
    ) -> None:
        # This is what the mask is for: one template per client, not one per release.
        line = f"agent {product}/{{}} connected"
        first = mine_patterns([_sample(line.format(version_a))])
        second = mine_patterns([_sample(line.format(version_b))])

        assert pattern_fingerprint(first[0].pattern) == pattern_fingerprint(second[0].pattern)


class TestHostMaskProperties(TestCase):
    """The cases above pin specific hostnames; these hold the rule over every shape of name.

    The host mask is a trade: it has to catch any real domain while leaving dotted code
    paths alone, and only the whole input space shows whether the suffix list draws that
    line in the right place.
    """

    @given(fqdn=_fqdn_st())
    @settings(max_examples=300, deadline=None)
    def test_any_hostname_collapses_to_one_placeholder(self, fqdn: str) -> None:
        patterns = mine_patterns([_sample(f"upstream {fqdn} refused")])

        # exact template: the whole name is consumed, not partly masked and partly literal
        assert patterns[0].pattern == "upstream <host> refused"

    @given(path=_dotted_code_path_st())
    @settings(max_examples=300, deadline=None)
    def test_dotted_paths_without_a_host_suffix_stay_literal(self, path: str) -> None:
        patterns = mine_patterns([_sample(f"handler in {path} module")])

        assert "<host>" not in patterns[0].pattern

    @given(host_a=_fqdn_st(), host_b=_fqdn_st())
    @settings(max_examples=300, deadline=None)
    def test_lines_differing_only_by_hostname_share_a_fingerprint(self, host_a: str, host_b: str) -> None:
        # This is what the mask is for. The patterns diff and the pattern list both key on
        # the fingerprint, so two hostnames that fingerprint apart show up as two templates.
        # The host sits in the message field: a JSON body with no message-like field is
        # canonicalized to its shape, which fingerprints identically whatever the host is and
        # would let an over-narrow host mask through.
        line = '{{"message":"upstream {} refused","upstream_cluster":"capture"}}'
        a = mine_patterns([_sample(line.format(host_a))])
        b = mine_patterns([_sample(line.format(host_b))])

        assert pattern_fingerprint(a[0].pattern) == pattern_fingerprint(b[0].pattern)


@st.composite
def _klog_header_st(draw: st.DrawFn, severity: str | None = None) -> str:
    """A klog / glog header: severity letter, MMDD, HH:MM:SS, optional microseconds."""
    severity = severity or draw(st.sampled_from("IWEF"))
    month = draw(st.integers(min_value=1, max_value=12))
    day = draw(st.integers(min_value=1, max_value=31))
    hour = draw(st.integers(min_value=0, max_value=23))
    minute = draw(st.integers(min_value=0, max_value=59))
    second = draw(st.integers(min_value=0, max_value=59))
    micros = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=999999)))
    header = f"{severity}{month:02d}{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
    return header if micros is None else f"{header}.{micros:06d}"


@st.composite
def _klog_header_pair_st(draw: st.DrawFn) -> tuple[str, str]:
    """Two headers sharing a severity letter, which is content rather than a variable."""
    severity = draw(st.sampled_from("IWEF"))
    return draw(_klog_header_st(severity)), draw(_klog_header_st(severity))


class TestKlogTimestampProperties(TestCase):
    """The cases above pin two dates; these hold the invariants over every date and time.

    A klog template has to stop moving when the clock moves, so both properties compare the
    same statement logged at two different instants.
    """

    @given(header=_klog_header_st())
    @settings(max_examples=400, deadline=None)
    def test_any_klog_header_collapses_to_a_severity_and_a_placeholder(self, header: str) -> None:
        patterns = mine_patterns([_sample(f"{header} 12 worker.go:31] task_retrying")])

        # exact template: the date is fully consumed and the severity letter survives
        assert patterns[0].pattern == f"{header[0]}<klogtime> <num> worker.go:<num>] task_retrying"

    @given(headers=_klog_header_pair_st())
    @settings(max_examples=400, deadline=None)
    def test_klog_lines_at_different_instants_share_a_fingerprint(self, headers: tuple[str, str]) -> None:
        # The patterns diff compares fingerprints across windows a week apart, so a date left
        # in the template turns one statement into a new/gone pair every day.
        line = "{} 12 worker.go:31] task_retrying"
        first = mine_patterns([_sample(line.format(headers[0]))])
        second = mine_patterns([_sample(line.format(headers[1]))])

        assert pattern_fingerprint(first[0].pattern) == pattern_fingerprint(second[0].pattern)

    @given(headers=_klog_header_pair_st())
    @settings(max_examples=400, deadline=None)
    def test_klog_match_regex_matches_a_sibling_at_another_instant(self, headers: tuple[str, str]) -> None:
        # The <klogtime> fragment has to cover every klog instant, or the
        # pivot from a klog pattern to its logs returns only the minute it was mined from.
        line = "{} 12 worker.go:31] task_retrying"
        patterns = mine_patterns([_sample(line.format(headers[0]))])

        assert patterns[0].match_regex is not None
        assert re.search(patterns[0].match_regex, line.format(headers[1]))


class TestTruncationProperties(TestCase):
    """The cases above pin specific cut points; these hold the invariants over all bodies.

    Truncation is where a body stops being the line a person wrote and becomes a prefix the
    miner invented, so both properties are about that prefix staying honest.
    """

    @given(body=st.one_of(_log_body_st(), _long_log_body_st()), cap=st.integers(min_value=8, max_value=600))
    @settings(max_examples=400, deadline=None)
    def test_prepared_body_holds_only_whole_tokens(self, body: str, cap: int) -> None:
        # A JSON body is reduced to its message-like field before collapsing, so the baseline
        # the prefix is measured against is the reduced body, not the raw line.
        collapsed = _WHITESPACE_RE.sub(" ", _prepare_json_body(body) or body).strip()

        prepared = _prepare_body(body, cap)

        assert len(prepared.text) <= cap
        # the flag has to mean "text is a prefix, not the whole line" for every input, since
        # compile_match_regex decides the end anchor from it alone
        assert prepared.truncated == (prepared.text != collapsed)
        if " " in collapsed[:cap]:
            # a cut back to a boundary can only drop whole tokens, never split one
            assert set(prepared.text.split(" ")) <= set(collapsed.split(" "))

    @given(body=st.one_of(_log_body_st(), _long_log_body_st(), _log_line_st()))
    @settings(max_examples=300, deadline=None)
    def test_mined_regex_matches_the_raw_body_it_came_from(self, body: str) -> None:
        # The pivot from a pattern to its logs runs match_regex against raw bodies in
        # ClickHouse, while mining sees a collapsed and truncated copy. Any disagreement
        # between the two produces a filter that returns nothing for a pattern the person is
        # looking at. A None regex is the honest outcome and is allowed.
        patterns = mine_patterns([_sample(body)])

        assert len(patterns) == 1
        if patterns[0].match_regex is not None:
            assert re.search(patterns[0].match_regex, body)

    @given(body=st.one_of(_log_body_st(), _long_log_body_st(), _log_line_st()))
    @settings(max_examples=300, deadline=None)
    def test_mined_literal_is_present_in_the_body(self, body: str) -> None:
        # match_literal is the icontains fallback when no regex compiles, so it has to be
        # text that really occurs in the line, not a fragment masking invented.
        patterns = mine_patterns([_sample(body)])

        literal = patterns[0].match_literal
        if literal is not None:
            assert literal in _WHITESPACE_RE.sub(" ", body)
