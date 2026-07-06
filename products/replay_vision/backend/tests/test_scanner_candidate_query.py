import datetime as dt

import pytest
from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin

from posthog.schema import EventPropertyFilter, PropertyOperator, RecordingPropertyFilter, RecordingsQuery

from posthog.hogql import ast

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.test.persons import create_person

from products.replay_vision.backend.queries.scanner_candidate_query import (
    BALANCED_SURFACING_THRESHOLD,
    DEFAULT_CANDIDATE_LIMIT,
    FOCUSED_SURFACING_THRESHOLD,
    SETTLE_INTERVAL,
    ScannerCandidateQuery,
)
from products.replay_vision.backend.queries.scanner_volume_estimate import (
    ESTIMATE_WINDOW_DAYS,
    estimate_scanner_session_volume,
)

_NOW = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)
_FROZEN_TIME = _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


# Construction-time sanitization (no DB needed).


def _make_query(**kwargs) -> ScannerCandidateQuery:
    return ScannerCandidateQuery(
        team=kwargs.pop("team", None),
        query=kwargs.pop("query", RecordingsQuery()),
        last_swept_at=kwargs.pop("last_swept_at", _NOW - dt.timedelta(hours=1)),
        sampling_rate=kwargs.pop("sampling_rate", 1.0),
        sampling_salt=kwargs.pop("sampling_salt", "scanner-1"),
        **kwargs,
    )


@pytest.mark.parametrize(
    "bad_last_swept_at",
    [
        "2026-01-01T00:00:00Z",
        12345,
        None,
    ],
)
def test_rejects_non_datetime_last_swept_at(bad_last_swept_at):
    with pytest.raises(TypeError):
        _make_query(last_swept_at=bad_last_swept_at)


def test_rejects_naive_last_swept_at():
    with pytest.raises(ValueError, match="timezone-aware"):
        _make_query(last_swept_at=dt.datetime(2026, 1, 1, 0, 0, 0))


def test_rejects_non_positive_candidate_limit():
    with pytest.raises(ValueError, match="candidate_limit must be positive"):
        _make_query(candidate_limit=0)
    with pytest.raises(ValueError, match="candidate_limit must be positive"):
        _make_query(candidate_limit=-5)


def test_rejects_non_positive_max_execution_time_seconds():
    with pytest.raises(ValueError, match="max_execution_time_seconds must be positive"):
        _make_query(max_execution_time_seconds=0)
    with pytest.raises(ValueError, match="max_execution_time_seconds must be positive"):
        _make_query(max_execution_time_seconds=-1)


@pytest.mark.parametrize(
    "raw,expected_internal",
    [
        (1.0, 1.0),
        (0.0, 0.0),
        (0.25, 0.25),
        (2.0, 1.0),
        (-0.1, 0.0),
    ],
)
def test_sampling_rate_clamped_on_construction(raw, expected_internal):
    q = _make_query(sampling_rate=raw)
    assert q._sampling_rate == expected_internal


@pytest.mark.parametrize(
    "stripped_field, value", [("date_to", "-1d"), ("limit", 17), ("offset", 42), ("after", "abc123")]
)
def test_strips_schedule_controlled_inputs(stripped_field, value):
    raw_query = RecordingsQuery(**{stripped_field: value})
    q = _make_query(query=raw_query)
    assert getattr(q._inner._query, stripped_field) is None


def test_inner_date_from_is_partition_prune_relative_to_watermark():
    last_swept_at = _NOW - dt.timedelta(hours=2)
    q = _make_query(query=RecordingsQuery(date_from="-30d"), last_swept_at=last_swept_at)
    assert q._inner._query.date_from is not None
    assert q._inner._query.date_from != "-30d"


# Sampling predicate (no DB).


def test_sampling_predicate_passthrough_at_full_rate():
    q = _make_query(sampling_rate=1.0)
    assert q._sampling_predicate() is None


@pytest.mark.parametrize("rate", [0.0, 0.00004])
def test_sampling_predicate_emits_false_below_one_bucket(rate):
    q = _make_query(sampling_rate=rate)
    expr = q._sampling_predicate()
    assert isinstance(expr, ast.Constant) and expr.value is False


@pytest.mark.parametrize(
    "rate, expected_threshold",
    [
        (0.25, 2500),
        # 0.29 * 10_000 is 2899.999… in floats; truncation used to shave a bucket.
        (0.29, 2900),
        (0.0001, 1),
    ],
)
def test_sampling_predicate_emits_modulo_compare_at_partial_rate(rate, expected_threshold):
    q = _make_query(sampling_rate=rate)
    expr = q._sampling_predicate()
    assert isinstance(expr, ast.CompareOperation)
    assert expr.op == ast.CompareOperationOp.Lt
    assert isinstance(expr.right, ast.Constant)
    assert expr.right.value == expected_threshold
    modulo = expr.left
    assert isinstance(modulo, ast.Call) and modulo.name == "modulo"
    city = modulo.args[0]
    assert isinstance(city, ast.Call) and city.name == "cityHash64"
    concat = city.args[0]
    assert isinstance(concat, ast.Call) and concat.name == "concat"
    # The per-scanner salt makes scanners draw independent samples instead of the identical session subset.
    assert isinstance(concat.args[1], ast.Constant) and concat.args[1].value == "scanner-1"


def test_surfacing_score_predicate_passthrough_in_comprehensive():
    q = _make_query(sampling_mode="comprehensive")
    assert q._surfacing_score_predicate() is None


@pytest.mark.parametrize(
    "mode,expected_threshold",
    [
        ("focused", FOCUSED_SURFACING_THRESHOLD),
        ("balanced", BALANCED_SURFACING_THRESHOLD),
    ],
)
def test_surfacing_score_predicate_emits_threshold(mode, expected_threshold):
    q = _make_query(sampling_mode=mode)
    expr = q._surfacing_score_predicate()
    assert isinstance(expr, ast.CompareOperation)
    assert expr.op == ast.CompareOperationOp.GtEq
    assert isinstance(expr.right, ast.Constant) and expr.right.value == expected_threshold


# Integration: actual ClickHouse query.


@freeze_time(_FROZEN_TIME)
class TestScannerCandidateQueryAgainstClickHouse(ClickhouseTestMixin):
    def setup_method(self, _method) -> None:
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

    @staticmethod
    def _produce(team_id: int, session_id: str, first: dt.datetime, last: dt.datetime, **kwargs) -> None:
        # Default to an eligibility-passing recording (>= MIN_ACTIVE active seconds) so tests exercising the watermark /
        # settle / sampling dimensions aren't incidentally dropped by the eligibility filter; override per-test as needed.
        kwargs.setdefault("active_milliseconds", 30_000)
        produce_replay_summary(
            team_id=team_id,
            session_id=session_id,
            first_timestamp=first.isoformat(),
            last_timestamp=last.isoformat(),
            **kwargs,
        )

    @pytest.mark.django_db
    def test_returns_sessions_in_chronological_order_with_session_end(self, team) -> None:
        settle_bound = _NOW - SETTLE_INTERVAL
        self._produce(
            team.id, "sess-a", settle_bound - dt.timedelta(minutes=20), settle_bound - dt.timedelta(minutes=10)
        )
        self._produce(
            team.id, "sess-b", settle_bound - dt.timedelta(minutes=40), settle_bound - dt.timedelta(minutes=30)
        )
        self._produce(
            team.id, "sess-c", settle_bound - dt.timedelta(minutes=10), settle_bound - dt.timedelta(minutes=5)
        )

        results = self._run(team=team, last_swept_at=_NOW - dt.timedelta(hours=2))

        assert [r.session_id for r in results] == ["sess-b", "sess-a", "sess-c"]
        assert results[0].session_end == settle_bound - dt.timedelta(minutes=30)
        assert results[2].session_end == settle_bound - dt.timedelta(minutes=5)

    @pytest.mark.django_db
    def test_watermark_excludes_sessions_ended_before_or_equal(self, team) -> None:
        last_swept_at = _NOW - dt.timedelta(hours=2)
        self._produce(team.id, "exactly-on-watermark", last_swept_at - dt.timedelta(minutes=10), last_swept_at)
        self._produce(
            team.id,
            "just-after-watermark",
            # >= 15s long so it clears the duration eligibility bound; session_end is still just past the watermark.
            last_swept_at - dt.timedelta(seconds=14),
            last_swept_at + dt.timedelta(seconds=1),
        )

        results = self._run(team=team, last_swept_at=last_swept_at)

        assert [r.session_id for r in results] == ["just-after-watermark"]

    @pytest.mark.django_db
    def test_settle_window_excludes_sessions_still_settling(self, team) -> None:
        settle_bound = _NOW - SETTLE_INTERVAL
        self._produce(
            team.id, "settled", settle_bound - dt.timedelta(minutes=10), settle_bound - dt.timedelta(seconds=1)
        )
        self._produce(team.id, "on-settle", settle_bound - dt.timedelta(minutes=5), settle_bound)
        self._produce(
            team.id, "still-settling", settle_bound - dt.timedelta(minutes=5), settle_bound + dt.timedelta(seconds=1)
        )

        results = self._run(team=team, last_swept_at=_NOW - dt.timedelta(hours=2))

        session_ids = {r.session_id for r in results}
        assert "settled" in session_ids
        assert "on-settle" in session_ids

        assert "still-settling" not in session_ids

    @pytest.mark.django_db
    def test_aggregates_multiple_rows_per_session(self, team) -> None:
        first = _NOW - dt.timedelta(hours=2)
        for i, last in enumerate(
            [
                _NOW - dt.timedelta(minutes=90),
                _NOW - dt.timedelta(minutes=60),
                _NOW - dt.timedelta(minutes=45),
            ]
        ):
            self._produce(
                team.id,
                "multi-row",
                first + dt.timedelta(seconds=i),
                last,
            )

        results = self._run(team=team, last_swept_at=_NOW - dt.timedelta(hours=4))

        assert len(results) == 1
        assert results[0].session_id == "multi-row"
        assert results[0].session_end == _NOW - dt.timedelta(minutes=45)

    @pytest.mark.django_db
    def test_zero_sampling_returns_empty(self, team) -> None:
        self._produce(team.id, "would-match", _NOW - dt.timedelta(hours=2), _NOW - dt.timedelta(minutes=40))
        results = self._run(team=team, last_swept_at=_NOW - dt.timedelta(hours=2), sampling_rate=0.0)
        assert results == []

    @pytest.mark.django_db
    def test_full_sampling_returns_all_candidates(self, team) -> None:
        for i in range(5):
            self._produce(
                team.id,
                f"sess-{i:02d}",
                _NOW - dt.timedelta(hours=2),
                _NOW - dt.timedelta(minutes=40 + i),
            )
        results = self._run(team=team, last_swept_at=_NOW - dt.timedelta(hours=2), sampling_rate=1.0)
        assert len(results) == 5

    @pytest.mark.django_db
    def test_partial_sampling_is_deterministic_per_session(self, team) -> None:
        for i in range(40):
            self._produce(
                team.id,
                f"stable-{i:04x}",
                _NOW - dt.timedelta(hours=2),
                _NOW - dt.timedelta(minutes=40 + i // 5),
            )
        first = self._run(team=team, last_swept_at=_NOW - dt.timedelta(hours=4), sampling_rate=0.5)
        second = self._run(team=team, last_swept_at=_NOW - dt.timedelta(hours=4), sampling_rate=0.5)
        assert [r.session_id for r in first] == [r.session_id for r in second]
        assert 0 < len(first) < 40

    @pytest.mark.django_db
    def test_excludes_deleted_recordings(self, team) -> None:
        self._produce(team.id, "kept", _NOW - dt.timedelta(hours=2), _NOW - dt.timedelta(minutes=40))
        self._produce(
            team.id,
            "deleted",
            _NOW - dt.timedelta(hours=2),
            _NOW - dt.timedelta(minutes=40),
            is_deleted=True,
        )
        results = self._run(team=team, last_swept_at=_NOW - dt.timedelta(hours=2))
        assert [r.session_id for r in results] == ["kept"]

    @pytest.mark.django_db
    def test_respects_candidate_limit(self, team) -> None:
        for i in range(10):
            self._produce(
                team.id,
                f"limit-{i:02d}",
                _NOW - dt.timedelta(hours=2),
                _NOW - dt.timedelta(minutes=40 + (10 - i)),  # limit-00 ends first, limit-09 last
            )
        results = self._run(team=team, last_swept_at=_NOW - dt.timedelta(hours=2), candidate_limit=3)
        assert [r.session_id for r in results] == ["limit-00", "limit-01", "limit-02"]

    @pytest.mark.django_db
    def test_filters_by_distinct_id(self, team) -> None:
        self._produce(
            team.id,
            "matched",
            _NOW - dt.timedelta(hours=2),
            _NOW - dt.timedelta(minutes=40),
            distinct_id="alice",
        )
        self._produce(
            team.id,
            "unmatched",
            _NOW - dt.timedelta(hours=2),
            _NOW - dt.timedelta(minutes=40),
            distinct_id="bob",
        )
        query = RecordingsQuery(distinct_ids=["alice"])
        results = self._run(team=team, query=query, last_swept_at=_NOW - dt.timedelta(hours=2))
        assert [r.session_id for r in results] == ["matched"]

    @pytest.mark.django_db
    def test_routes_dollar_lib_event_property_to_having(self, team) -> None:
        self._produce(
            team.id,
            "web",
            _NOW - dt.timedelta(hours=2),
            _NOW - dt.timedelta(minutes=40),
            snapshot_library="web",
        )
        self._produce(
            team.id,
            "mobile",
            _NOW - dt.timedelta(hours=2),
            _NOW - dt.timedelta(minutes=40),
            snapshot_library="posthog-ios",
        )
        query = RecordingsQuery(
            properties=[EventPropertyFilter(key="$lib", operator=PropertyOperator.EXACT, value="web")]
        )
        results = self._run(team=team, query=query, last_swept_at=_NOW - dt.timedelta(hours=2))
        assert [r.session_id for r in results] == ["web"]

    @pytest.mark.django_db
    def test_honors_having_predicate_from_recordings_query(self, team) -> None:
        self._produce(
            team.id,
            "long",
            _NOW - dt.timedelta(hours=2),
            _NOW - dt.timedelta(minutes=40),
            active_milliseconds=120_000,
        )
        self._produce(
            team.id,
            "short",
            _NOW - dt.timedelta(hours=2),
            _NOW - dt.timedelta(minutes=40),
            active_milliseconds=5_000,
        )
        query = RecordingsQuery(
            having_predicates=[
                RecordingPropertyFilter(type="recording", key="active_seconds", operator=PropertyOperator.GTE, value=30)
            ]
        )
        results = self._run(team=team, query=query, last_swept_at=_NOW - dt.timedelta(hours=2))
        assert [r.session_id for r in results] == ["long"]

    @pytest.mark.django_db
    def test_excludes_recordings_the_scan_would_mark_ineligible(self, team) -> None:
        # Recordings the scan rejects as too short / too idle / too long are dropped before becoming candidates (the
        # scan re-checks them authoritatively). All four end before the settle bound, so settle isn't the reason.
        sb = _NOW - SETTLE_INTERVAL

        def produce(session_id: str, start: dt.datetime, duration_s: int, active_ms: int) -> None:
            self._produce(
                team.id, session_id, start, start + dt.timedelta(seconds=duration_s), active_milliseconds=active_ms
            )

        produce("too-short", sb - dt.timedelta(minutes=10), 10, 10_000)  # 10s wall < 15s min duration
        produce("too-idle", sb - dt.timedelta(minutes=12), 60, 5_000)  # 5s active < 10s min active
        produce("too-long", sb - dt.timedelta(minutes=80), 4200, 3_700_000)  # 3700s active > 3600s max active
        produce("eligible", sb - dt.timedelta(minutes=20), 60, 30_000)  # 60s wall, 30s active

        results = {r.session_id for r in self._run(team=team, last_swept_at=_NOW - dt.timedelta(hours=2))}
        assert results == {"eligible"}

    @pytest.mark.django_db
    def test_volume_estimate_counts_only_eligible_recordings(self, team) -> None:
        # The estimate shares eligibility_predicates() with the candidate query, so the forecast counts the same
        # eligible set the sweep selects instead of over-counting recordings the scan would reject.
        recent = _NOW - dt.timedelta(days=2)
        self._produce(team.id, "too-short", recent, recent + dt.timedelta(seconds=10), active_milliseconds=10_000)
        self._produce(team.id, "eligible", recent, recent + dt.timedelta(seconds=60), active_milliseconds=30_000)

        estimate = estimate_scanner_session_volume(team=team, query=RecordingsQuery())

        assert estimate.matched_sessions == 1

    @pytest.mark.django_db
    def test_volume_estimate_window_is_exactly_30_days(self, team) -> None:
        # A relative "-30d" date_from truncates to start-of-day, counting up to 31 days against the /30 divisor.
        bound = _NOW - dt.timedelta(days=ESTIMATE_WINDOW_DAYS)
        self._produce(
            team.id,
            "same-day-but-outside",
            bound - dt.timedelta(hours=6, seconds=60),
            bound - dt.timedelta(hours=6),
            active_milliseconds=30_000,
        )
        self._produce(
            team.id,
            "inside",
            _NOW - dt.timedelta(days=2),
            _NOW - dt.timedelta(days=2) + dt.timedelta(seconds=60),
            active_milliseconds=30_000,
        )

        estimate = estimate_scanner_session_volume(team=team, query=RecordingsQuery())

        assert estimate.matched_sessions == 1

    @pytest.mark.django_db
    def test_volume_estimate_divisor_stays_full_for_old_but_quiet_teams(self, team) -> None:
        # The bounded earliest-recording probe must not shrink the divisor for teams older than the window.
        old = _NOW - dt.timedelta(days=40)
        self._produce(team.id, "old-session", old, old + dt.timedelta(seconds=60), active_milliseconds=30_000)

        estimate = estimate_scanner_session_volume(team=team, query=RecordingsQuery())

        assert estimate.matched_sessions == 0
        assert estimate.effective_window_days == ESTIMATE_WINDOW_DAYS

    @pytest.mark.django_db
    def test_filter_test_accounts_excludes_internal_users(self, team) -> None:
        # test_account_filters are exclusion-style — the operator picks the accounts to drop.
        team.test_account_filters = [
            {
                "key": "email",
                "operator": "not_icontains",
                "value": "@posthog.com",
                "type": "person",
            }
        ]
        team.save(update_fields=["test_account_filters"])
        create_person(team=team, distinct_ids=["internal"], properties={"email": "hi@posthog.com"})
        create_person(team=team, distinct_ids=["external"], properties={"email": "hi@example.com"})

        self._produce(
            team.id,
            "internal-session",
            _NOW - dt.timedelta(hours=2),
            _NOW - dt.timedelta(minutes=40),
            distinct_id="internal",
        )
        self._produce(
            team.id,
            "external-session",
            _NOW - dt.timedelta(hours=2),
            _NOW - dt.timedelta(minutes=40),
            distinct_id="external",
        )

        query = RecordingsQuery(filter_test_accounts=True)
        results = self._run(team=team, query=query, last_swept_at=_NOW - dt.timedelta(hours=2))
        assert [r.session_id for r in results] == ["external-session"]

    @pytest.mark.django_db
    def test_long_running_session_within_24h_cap_is_returned(self, team) -> None:
        last_swept_at = _NOW - dt.timedelta(hours=1)
        self._produce(
            team.id,
            "long-running",
            _NOW - dt.timedelta(hours=10),
            last_swept_at + dt.timedelta(minutes=1),
        )

        results = self._run(team=team, last_swept_at=last_swept_at)

        assert [r.session_id for r in results] == ["long-running"]

    @pytest.mark.django_db
    def test_straddling_session_keeps_full_aggregates(self, team) -> None:
        last_swept_at = _NOW - dt.timedelta(hours=1)
        # Three rows totalling 36 active seconds — passes the 30s HAVING bound only if all rows are aggregated.
        for last_offset_minutes, ms in (
            (75, 12_000),
            (45, 12_000),
            (40, 12_000),
        ):
            self._produce(
                team.id,
                "straddler",
                _NOW - dt.timedelta(minutes=80),
                _NOW - dt.timedelta(minutes=last_offset_minutes),
                active_milliseconds=ms,
            )
        # Control: only 18s of activity — should fail HAVING.
        self._produce(
            team.id,
            "post-watermark-short",
            _NOW - dt.timedelta(minutes=50),
            _NOW - dt.timedelta(minutes=40),
            active_milliseconds=18_000,
        )

        query = RecordingsQuery(
            having_predicates=[
                RecordingPropertyFilter(type="recording", key="active_seconds", operator=PropertyOperator.GTE, value=30)
            ]
        )
        results = self._run(team=team, query=query, last_swept_at=last_swept_at)

        assert [r.session_id for r in results] == ["straddler"]

    @pytest.mark.django_db
    def test_session_still_settling_is_not_emitted(self, team) -> None:
        settle_bound = _NOW - SETTLE_INTERVAL
        # Two rows: one outside settle, one inside — session is still live.
        self._produce(
            team.id,
            "still-live",
            settle_bound - dt.timedelta(hours=2),
            settle_bound - dt.timedelta(minutes=30),
        )
        self._produce(
            team.id,
            "still-live",
            settle_bound - dt.timedelta(hours=2),
            settle_bound + dt.timedelta(minutes=1),
        )

        results = self._run(team=team, last_swept_at=_NOW - dt.timedelta(hours=4))

        assert results == []

    @pytest.mark.django_db
    def test_excludes_overlong_session_ids(self, team) -> None:
        # Attacker-supplied session_ids over the 128-char cap would otherwise wedge wire-payload validation.
        self._produce(team.id, "x" * 129, _NOW - dt.timedelta(hours=2), _NOW - dt.timedelta(minutes=40))
        self._produce(team.id, "ok", _NOW - dt.timedelta(hours=2), _NOW - dt.timedelta(minutes=40))

        results = self._run(team=team, last_swept_at=_NOW - dt.timedelta(hours=2))

        assert [r.session_id for r in results] == ["ok"]

    @pytest.mark.django_db
    def test_excludes_recordings_past_retention(self, team) -> None:
        self._produce(
            team.id,
            "expired",
            _NOW - dt.timedelta(days=120),
            _NOW - dt.timedelta(days=120) + dt.timedelta(minutes=5),
            retention_period_days=0,
        )
        self._produce(
            team.id,
            "fresh",
            _NOW - dt.timedelta(hours=2),
            _NOW - dt.timedelta(minutes=40),
            retention_period_days=30,
        )

        results = self._run(team=team, last_swept_at=_NOW - dt.timedelta(days=365))

        assert [r.session_id for r in results] == ["fresh"]

    @pytest.mark.django_db
    def test_keyset_resume_includes_ties_after_last_seen(self, team) -> None:
        boundary = _NOW - dt.timedelta(hours=1)
        for sid in ("aaa", "bbb", "ccc"):
            self._produce(team.id, sid, boundary - dt.timedelta(minutes=10), boundary)

        results = self._run(
            team=team,
            last_swept_at=boundary,
            last_seen_session_id="aaa",
        )

        assert [r.session_id for r in results] == ["bbb", "ccc"]

    @pytest.mark.django_db
    def test_keyset_resume_still_includes_strictly_later_sessions(self, team) -> None:
        boundary = _NOW - dt.timedelta(hours=1)
        # Names ordered so the resumed id comes after the skipped one lexicographically.
        self._produce(team.id, "aaa-tied-skipped", boundary - dt.timedelta(minutes=10), boundary)
        self._produce(team.id, "bbb-tied-resumed", boundary - dt.timedelta(minutes=10), boundary)
        self._produce(
            team.id, "ccc-strictly-later", boundary - dt.timedelta(minutes=5), boundary + dt.timedelta(seconds=1)
        )

        results = self._run(team=team, last_swept_at=boundary, last_seen_session_id="aaa-tied-skipped")

        assert sorted(r.session_id for r in results) == ["bbb-tied-resumed", "ccc-strictly-later"]

    @pytest.mark.django_db
    def test_returns_empty_list_when_no_sessions(self, team) -> None:
        results = self._run(team=team, last_swept_at=_NOW - dt.timedelta(hours=2))
        assert results == []

    @staticmethod
    def _run(
        *,
        team,
        last_swept_at: dt.datetime,
        query: RecordingsQuery | None = None,
        sampling_rate: float = 1.0,
        sampling_salt: str = "scanner-1",
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        last_seen_session_id: str | None = None,
    ):
        return ScannerCandidateQuery(
            team=team,
            query=query if query is not None else RecordingsQuery(),
            last_swept_at=last_swept_at,
            sampling_rate=sampling_rate,
            sampling_salt=sampling_salt,
            candidate_limit=candidate_limit,
            last_seen_session_id=last_seen_session_id,
        ).run()
