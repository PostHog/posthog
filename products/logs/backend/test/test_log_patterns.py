import re
import datetime as dt
from itertools import zip_longest

from unittest import TestCase

from hypothesis import (
    given,
    settings,
    strategies as st,
)
from parameterized import parameterized

from products.logs.backend.log_patterns import (
    _MASKING_INSTRUCTIONS,
    _PLACEHOLDER_PATTERNS,
    LogSample,
    compile_match_regex,
    extract_match_literal,
    mine_patterns,
    pattern_fingerprint,
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

    def test_same_statement_on_different_dates_shares_fingerprint(self) -> None:
        # The patterns diff compares fingerprints across two windows (default: one week
        # apart). A timestamp fragment surviving masking becomes a literal run, so the
        # same log statement would fingerprint differently and show up as a false
        # new/gone pair.
        monday = mine_patterns([_sample("2026-08-12T08:10:43.397557Z task_retrying attempt=3")])
        week_later = mine_patterns([_sample("2026-08-19T09:04:17.112233Z task_retrying attempt=7")])

        assert pattern_fingerprint(monday[0].pattern) == pattern_fingerprint(week_later[0].pattern)

    def test_match_regex_matches_siblings_with_different_timestamps(self) -> None:
        # An unmasked timestamp baked into match_regex narrows the "view matching logs"
        # pivot to the single line the pattern was mined from.
        patterns = mine_patterns([_sample("task_retrying at 2026-08-12T08:10:43.397557Z scheduled")])

        assert patterns[0].match_regex is not None
        assert re.search(patterns[0].match_regex, "task_retrying at 2026-08-19T14:02:11.000001Z scheduled")


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
            ("agent Chrome/<version> connected", "agent Chrome/139.0.0.0 connected"),
            ("path /api/v1/users?id=<num> hit", "path /api/v1/users?id=42 hit"),
            ("job <timestamp> finished", "job 2026-08-12T08:10:43.397557Z finished"),
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


_version_st = st.lists(st.integers(min_value=0, max_value=9999), min_size=2, max_size=4).map(
    lambda parts: ".".join(map(str, parts))
)
_decimal_context_st = st.sampled_from(["duration_ms=", "ratio=", "load ", "p95="])
_slash_version_st = st.tuples(_product_st, _version_st).map(lambda t: f"{t[0]}/{t[1]}")
_variable_token_st = st.one_of(
    _uuid_st, _hex_0x_st, _hex_bare_st, _num_st, _timestamp_st(), _ipv4_st, _slash_version_st
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

        # exact template: two to four parts become one placeholder, not one <num> per part
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
