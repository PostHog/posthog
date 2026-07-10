import re
import json
import datetime as dt

from unittest import TestCase

from hypothesis import (
    HealthCheck,
    example,
    given,
    settings,
    strategies as st,
)

from products.logs.backend.log_patterns import LogSample, _prepare_json_body, mine_patterns

# PostHog CI runs the backend suite with pytest-rerunfailures (--reruns 2). A rerun
# re-instantiates the TestCase, so a genuinely-failing @given method is re-invoked from a
# fresh instance, which trips hypothesis's differing_executors health check and masks the
# real falsifying example. These tests are pure functions with no shared state, so
# cross-instance reruns are benign - suppress the check so a regression surfaces its
# falsifying example.
_SUPPRESSED_HEALTH_CHECKS = [HealthCheck.differing_executors]

_TS = dt.datetime(2026, 6, 23, 12, 0, 0, tzinfo=dt.UTC)


def _samples(bodies: list[str]) -> list[LogSample]:
    return [LogSample(body=body, severity_text="info", service_name="api", timestamp=_TS) for body in bodies]


# Log bodies are arbitrary user-controlled text. Include the mining placeholder vocabulary
# and regex metacharacters in the alphabet so generated bodies can collide with the miner's
# own tokens ("<num>", "<*>") - the injection-shaped inputs example tables never enumerate.
_body_text = st.text(
    alphabet=st.one_of(
        st.characters(codec="utf-8", exclude_categories=("Cs",)),
        st.sampled_from(list('<>*nums."\\^$()[]{}+?|')),
    ),
    max_size=200,
)

_json_scalars = st.one_of(st.none(), st.booleans(), st.integers(), st.floats(allow_nan=False), st.text(max_size=30))
_json_values = st.one_of(
    _json_scalars,
    st.lists(_json_scalars, max_size=3),
    st.dictionaries(st.text(min_size=1, max_size=15), _json_scalars, max_size=3),
)
_json_objects = st.dictionaries(st.text(min_size=1, max_size=15), _json_values, min_size=1, max_size=6)


class TestLogPatternsProperties(TestCase):
    @given(bodies=st.lists(_body_text, min_size=1, max_size=8))
    @settings(max_examples=200, deadline=None, suppress_health_check=_SUPPRESSED_HEALTH_CHECKS)
    def test_mining_arbitrary_bodies_never_raises_and_respects_the_length_cap(self, bodies: list[str]) -> None:
        patterns = mine_patterns(_samples(bodies), max_patterns=50)

        assert len(patterns) <= 50
        for pattern in patterns:
            for kept in pattern.examples:
                assert len(kept.body) <= 512

    # Pinned adversarial inputs: log content that collides with the miner's own placeholder
    # vocabulary must never yield a predicate that matches nothing (the template's "<num>" is
    # compiled as \d+ while the raw line holds the literal text - validation must withhold it).
    @example(bodies=["literal <num> in a log line", "literal <num> in a log line again"])
    @example(bodies=["wildcard <*> live in body text"])
    @example(bodies=['{"message": "user <uuid> said hi"}'])
    @given(bodies=st.lists(_body_text, min_size=1, max_size=8))
    @settings(max_examples=200, deadline=None, suppress_health_check=_SUPPRESSED_HEALTH_CHECKS)
    def test_shipped_predicates_match_the_raw_bodies_they_were_mined_from(self, bodies: list[str]) -> None:
        # The contract the "view matching logs" pivot rests on: a predicate is only offered if
        # it matches the raw rows it came from, no matter what the bodies contain - including
        # text that collides with the placeholder vocabulary or regex metacharacters. From
        # outside we can't see which input rows fed which cluster, so the property asserts the
        # implied form - some raw input matches; a shipped predicate matching zero inputs is
        # exactly the "filters to nothing in ClickHouse" bug.
        for pattern in mine_patterns(_samples(bodies)):
            if pattern.match_regex is not None:
                compiled = re.compile(pattern.match_regex)
                assert any(compiled.search(body) for body in bodies)
            if pattern.match_literal is not None:
                needle = pattern.match_literal.lower()
                assert any(needle in body.lower() for body in bodies)

    @given(obj=_json_objects, seed=st.randoms(use_true_random=False))
    @settings(max_examples=200, deadline=None, suppress_health_check=_SUPPRESSED_HEALTH_CHECKS)
    def test_shape_canonicalization_is_key_order_and_value_invariant(self, obj: dict, seed) -> None:
        # Only shape-path objects (no extractable message) exercise canonicalization.
        keys = list(obj)
        seed.shuffle(keys)
        shuffled = {key: obj[key] for key in keys}

        a = _prepare_json_body(json.dumps(obj))
        b = _prepare_json_body(json.dumps(shuffled))

        assert a == b

    @given(obj=_json_objects, message=st.text(min_size=1, max_size=100).filter(lambda s: s.strip()))
    @settings(max_examples=200, deadline=None, suppress_health_check=_SUPPRESSED_HEALTH_CHECKS)
    def test_message_extraction_returns_the_message_verbatim(self, obj: dict, message: str) -> None:
        obj["message"] = message

        assert _prepare_json_body(json.dumps(obj)) == message
