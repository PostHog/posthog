from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.parser import parse_expr

from posthog.cdp.filters import compile_filters_expr
from posthog.models import Team

from products.workflows.backend.services.wake_plan import analyze_wait_condition

from common.hogvm.python.execute import execute_bytecode

# The condition from the one production flow found to depend on the polling re-check: wake a day
# before a trial expiration date stored on the person.
PRODUCTION_TRIAL_CONDITION = (
    "toUnixTimestamp(now()) >= toUnixTimestamp(toDateTime(person.properties.trial_expiration_at)) - 86400"
)


class TestWakePlan(SimpleTestCase):
    def _plan(self, expr: str):
        # Analysis is pure: it walks the compiled expression and emits bytecode, never touching the
        # database, so team_id only has to be an id-shaped value.
        return analyze_wait_condition(parse_expr(expr), team_id=1)

    def test_production_trial_condition_yields_a_timer(self):
        plan = self._plan(PRODUCTION_TRIAL_CONDITION)

        assert plan.unsupported_reason is None
        assert plan.needs_polling is False
        assert len(plan.timers) == 1
        # The timer inverts the comparison, so it must resolve the stored date rather than re-read
        # the clock. A timer containing now() would evaluate to "always now" and fire immediately.
        assert "fromUnixTimestamp" in plan.timers[0]
        assert "now" not in plan.timers[0]
        assert "trial_expiration_at" in plan.timers[0]
        # The person stream still matters: if the stored date is edited mid-wait, the timer has to
        # be recomputed, and the person update is what triggers that.
        assert plan.streams == ["person"]

    def test_production_trial_timer_executes_to_a_day_before_expiration(self):
        # The load-bearing claim of the whole design: the emitted timer is evaluable by the HogVM
        # and yields the instant the condition flips. Asserting on bytecode contents alone would
        # pass even if the expression were unrunnable or off by a term.
        plan = self._plan(PRODUCTION_TRIAL_CONDITION)

        result = execute_bytecode(
            plan.timers[0],
            globals={"person": {"properties": {"trial_expiration_at": "2026-08-01T12:00:00Z"}}},
        )

        # A trial expiring Aug 1 12:00Z must wake the wait Jul 31 12:00Z, one day earlier.
        # fromUnixTimestamp yields a HogDateTime, which is the shape the executor parks on.
        assert result.result["dt"] == datetime(2026, 7, 31, 12, 0, tzinfo=UTC).timestamp()

    def test_analyzes_the_expression_the_serializer_actually_compiles(self):
        # The analyzer runs on compile_filters_expr output in production, not on a hand-parsed
        # string. That path wraps and rewrites the hogql property (property_to_expr), so a plan
        # derived from parse_expr proves nothing about the real one. Regression this catches: a
        # wrapping change that hides the clock call, silently reclassifying a timed wait as
        # stream-only and dropping its wake once the poll is gone.
        # Only the few attributes compile_filters_expr touches; no DB row needed.
        team = cast(Team, SimpleNamespace(id=1, project_id=1, test_account_filters=[], timezone="UTC"))
        filters = {
            "source": "events",
            "properties": [{"key": PRODUCTION_TRIAL_CONDITION, "type": "hogql", "value": None}],
        }

        plan = analyze_wait_condition(compile_filters_expr(filters, team, actions={}), team_id=team.id)

        assert plan.unsupported_reason is None
        assert len(plan.timers) == 1
        result = execute_bytecode(
            plan.timers[0],
            globals={"person": {"properties": {"trial_expiration_at": "2026-08-01T12:00:00Z"}}},
        )
        assert result.result["dt"] == datetime(2026, 7, 31, 12, 0, tzinfo=UTC).timestamp()

    @parameterized.expand(
        [
            ("one_day_notice", "1", datetime(2026, 7, 31, 12, 0)),
            ("three_day_notice", "3", datetime(2026, 7, 29, 12, 0)),
        ]
    )
    def test_offset_read_from_a_second_person_property(self, _name: str, notice: str, expected: datetime):
        # The live production condition takes its offset from a *second* person property rather than
        # a literal, so the timer reads two. The threshold side is opaque to the analyzer, so this
        # works for free - but a regression that dropped the offset term would still emit a
        # plausible timer, just firing on the wrong day, which only a value assertion catches.
        #
        # The unset-property path (coalesce falling back to 1) is deliberately not asserted here:
        # toInt(null) returns null in the TypeScript VM that runs this in production but raises in
        # the Python VM used by this test, so asserting it would test the wrong runtime.
        plan = self._plan(
            "toUnixTimestamp(now()) >= toUnixTimestamp(toDateTime(person.properties.trial_expiration_at)) "
            "- coalesce(toInt(person.properties.trial_reminder_days), 1) * 86400"
        )

        assert plan.unsupported_reason is None
        assert len(plan.timers) == 1
        result = execute_bytecode(
            plan.timers[0],
            globals={
                "person": {"properties": {"trial_expiration_at": "2026-08-01T12:00:00Z", "trial_reminder_days": notice}}
            },
        )
        assert result.result["dt"] == expected.replace(tzinfo=UTC).timestamp()

    def test_days_since_condition_executes_to_the_offset_instant(self):
        # Production shape from another flow: "14 days since last seen". dateDiff grows with the
        # clock, so it flips at last_seen_at + 14 days.
        plan = self._plan("dateDiff('day', toDateTime(person.properties.last_seen_at), now()) >= 14")

        assert plan.unsupported_reason is None
        result = execute_bytecode(
            plan.timers[0],
            globals={"person": {"properties": {"last_seen_at": "2026-07-01T09:00:00Z"}}},
        )
        assert result.result["dt"] == datetime(2026, 7, 15, 9, 0, tzinfo=UTC).timestamp()

    def test_days_until_condition_executes_to_the_offset_instant(self):
        # Production shape: "within 2 days of trial end". dateDiff shrinks as the clock advances, so
        # it flips at trial_ends_at minus 2 days. Getting the direction wrong here would park the
        # wait two days late, past the moment it was supposed to fire.
        plan = self._plan("dateDiff('day', now(), toDateTime(person.properties.trial_ends_at)) <= 2")

        assert plan.unsupported_reason is None
        result = execute_bytecode(
            plan.timers[0],
            globals={"person": {"properties": {"trial_ends_at": "2026-08-10T00:00:00Z"}}},
        )
        assert result.result["dt"] == datetime(2026, 8, 8, 0, 0, tzinfo=UTC).timestamp()

    @parameterized.expand(
        [
            # Reversed against the direction the expression moves: "days since" falling below a
            # threshold, or "days until" climbing above one, never starts holding as time passes.
            ("days_since_reversed", "dateDiff('day', person.properties.last_seen_at, now()) <= 14"),
            ("days_until_reversed", "dateDiff('day', now(), person.properties.trial_ends_at) >= 2"),
            # The clock in the unit argument, or at both ends, has no single flip instant.
            ("clock_in_unit", "dateDiff(person.properties.unit, now(), now()) <= 2"),
        ]
    )
    def test_uninvertible_datediff_shapes_fail_closed(self, _name: str, expr: str):
        plan = self._plan(expr)

        assert plan.unsupported_reason is not None
        assert plan.timers == []

    @parameterized.expand(
        [
            ("clock_left_gte", "toUnixTimestamp(now()) >= toUnixTimestamp(person.properties.due_at)"),
            ("clock_left_gt", "toUnixTimestamp(now()) > toUnixTimestamp(person.properties.due_at)"),
            ("bare_now_gte", "now() >= toDateTime(person.properties.due_at)"),
            ("clock_right_lte", "toUnixTimestamp(person.properties.due_at) <= toUnixTimestamp(now())"),
            ("clock_right_lt", "toDateTime(person.properties.due_at) < now()"),
        ]
    )
    def test_invertible_thresholds_produce_one_timer(self, _name: str, expr: str):
        plan = self._plan(expr)

        assert plan.unsupported_reason is None
        assert len(plan.timers) == 1
        assert "now" not in plan.timers[0]

    @parameterized.expand(
        [
            # Reversed comparisons never flip from false to true as the clock advances, so treating
            # them as a threshold would park a wait that should be woken some other way.
            ("reversed_lte", "toUnixTimestamp(now()) <= toUnixTimestamp(person.properties.due_at)"),
            ("reversed_gte", "toDateTime(person.properties.due_at) >= now()"),
            # Equality on a continuous clock is never reliably observable.
            ("equality", "toUnixTimestamp(now()) == toUnixTimestamp(person.properties.due_at)"),
            # The clock on both sides has no single flip instant.
            ("clock_both_sides", "toUnixTimestamp(now()) >= toUnixTimestamp(now()) - 60"),
            # Buried in arithmetic or a non-monotonic call, the flip instant isn't recoverable.
            ("clock_in_arithmetic", "person.properties.count > toUnixTimestamp(now()) - 86400"),
            ("clock_in_unknown_call", "toDayOfWeek(now()) == 1"),
            ("negated", "not (toUnixTimestamp(now()) >= toUnixTimestamp(person.properties.due_at))"),
        ]
    )
    def test_uninvertible_clock_references_fail_closed(self, _name: str, expr: str):
        plan = self._plan(expr)

        assert plan.unsupported_reason is not None
        assert plan.needs_polling is True
        assert plan.timers == []

    def test_condition_without_clock_needs_no_timer(self):
        plan = self._plan("person.properties.rc_subscription_status == 'active'")

        assert plan.unsupported_reason is None
        assert plan.needs_polling is False
        assert plan.timers == []
        assert plan.streams == ["person"]

    def test_event_condition_reports_the_event_stream(self):
        plan = self._plan("event == 'subscription created'")

        assert plan.timers == []
        assert plan.streams == ["event"]

    def test_boolean_structure_collects_every_threshold(self):
        # Two independent clock thresholds plus a person predicate. Every threshold must be
        # collected: dropping one would let the wait sleep through the instant it flips.
        plan = self._plan(
            "(toUnixTimestamp(now()) >= toUnixTimestamp(person.properties.a) "
            "or toUnixTimestamp(now()) >= toUnixTimestamp(person.properties.b)) "
            "and person.properties.status == 'trial'"
        )

        assert plan.unsupported_reason is None
        assert len(plan.timers) == 2
        assert plan.streams == ["person"]

    def test_one_uninvertible_branch_poisons_the_whole_condition(self):
        # A recognizable threshold ANDed with an unrecognizable clock reference must not report a
        # usable plan: the wait would be parked on the good threshold and never re-checked for the
        # other, which is exactly the silent breakage this analysis exists to prevent.
        plan = self._plan(
            "toUnixTimestamp(now()) >= toUnixTimestamp(person.properties.due_at) and toDayOfWeek(now()) == 1"
        )

        assert plan.unsupported_reason is not None
        assert plan.timers == []
