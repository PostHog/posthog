from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from products.tasks.backend.logic.services.sandbox_pricing import (
    ComputeRateCard,
    ComputeRateCardConfigurationError,
    calculate_sandbox_compute_cost,
    validate_compute_rate_cards,
    validate_reporting_window,
)

EFFECTIVE_AT = datetime(2026, 8, 1, tzinfo=UTC)
NEXT_RATE_AT = datetime(2026, 9, 1, tzinfo=UTC)
RATE_V1 = ComputeRateCard(
    version="2026-08-01",
    effective_at=EFFECTIVE_AT,
    expires_at=NEXT_RATE_AT,
    cpu_core_second_usd=Decimal("0.000011"),
    memory_gib_second_usd=Decimal("0.0000021"),
)
RATE_V2 = ComputeRateCard(
    version="2026-09-01",
    effective_at=NEXT_RATE_AT,
    expires_at=None,
    cpu_core_second_usd=Decimal("0.000013"),
    memory_gib_second_usd=Decimal("0.0000024"),
)


def _session(**overrides):
    defaults = {
        "created_at": EFFECTIVE_AT,
        "user_attributed_at": EFFECTIVE_AT,
        "ended_at": EFFECTIVE_AT + timedelta(seconds=10),
        "ttl_expires_at": EFFECTIVE_AT + timedelta(hours=6),
        "vm_runtime": False,
        "burstable": False,
        "cpu_cores": 4.0,
        "memory_gb": 16.0,
        "cpu_request_cores": None,
        "memory_request_mb": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _calculate(session, start=EFFECTIVE_AT, end=EFFECTIVE_AT + timedelta(days=1), **kwargs):
    return calculate_sandbox_compute_cost(session, start, end, rate_cards=(RATE_V1, RATE_V2), **kwargs)


def test_prices_closed_session_from_user_attribution():
    session = _session(
        created_at=EFFECTIVE_AT,
        user_attributed_at=EFFECTIVE_AT + timedelta(seconds=20),
        ended_at=EFFECTIVE_AT + timedelta(seconds=30),
    )

    cost = _calculate(session)

    assert cost.billable_seconds == 10
    assert cost.cpu_core_seconds == Decimal("40.0")
    assert cost.memory_gib_seconds == Decimal("160.0")


def test_unattributed_prewarmed_session_is_not_priced():
    cost = _calculate(_session(user_attributed_at=None, ended_at=None))

    assert cost.billable_seconds == 0
    assert cost.total_cost_usd == 0


def test_claimed_prewarmed_session_starts_at_attribution():
    cost = _calculate(
        _session(
            created_at=EFFECTIVE_AT,
            user_attributed_at=EFFECTIVE_AT + timedelta(hours=1),
            ended_at=EFFECTIVE_AT + timedelta(hours=1, seconds=5),
        )
    )

    assert cost.billable_seconds == 5


def test_open_session_clamps_to_calculation_time_and_ttl():
    session = _session(ended_at=None, ttl_expires_at=EFFECTIVE_AT + timedelta(seconds=12))

    before_ttl = _calculate(session, calculated_at=EFFECTIVE_AT + timedelta(seconds=7))
    after_ttl = _calculate(session, calculated_at=EFFECTIVE_AT + timedelta(seconds=20))

    assert before_ttl.billable_seconds == 7
    assert after_ttl.billable_seconds == 12


def test_reporting_window_clips_cross_period_session_without_negative_duration():
    session = _session(
        user_attributed_at=EFFECTIVE_AT - timedelta(hours=1),
        ended_at=EFFECTIVE_AT + timedelta(hours=2),
    )

    cost = _calculate(session, EFFECTIVE_AT, EFFECTIVE_AT + timedelta(hours=1))
    outside = _calculate(session, EFFECTIVE_AT + timedelta(days=1), EFFECTIVE_AT + timedelta(days=2))

    assert cost.billable_seconds == 3600
    assert outside.billable_seconds == 0


@pytest.mark.parametrize(
    "duration, expected",
    [(timedelta(microseconds=1), 1), (timedelta(seconds=1), 1), (timedelta(seconds=1, microseconds=1), 2)],
)
def test_rounds_each_session_duration_up_to_a_whole_second(duration, expected):
    assert _calculate(_session(ended_at=EFFECTIVE_AT + duration)).billable_seconds == expected


@pytest.mark.parametrize(
    "resource_overrides, expected_cpu_core_seconds, expected_memory_gib_seconds",
    [
        ({"cpu_request_cores": 0.5}, Decimal("5.0"), Decimal("160.0")),
        ({"memory_request_mb": 1024}, Decimal("40.0"), Decimal("10")),
        ({}, Decimal("40.0"), Decimal("160.0")),
    ],
)
def test_selects_cpu_and_memory_request_quantities_independently(
    resource_overrides, expected_cpu_core_seconds, expected_memory_gib_seconds
):
    cost = _calculate(_session(**resource_overrides))

    assert cost.cpu_core_seconds == expected_cpu_core_seconds
    assert cost.memory_gib_seconds == expected_memory_gib_seconds


def test_cpu_limit_does_not_change_cost_when_request_is_unchanged():
    smaller_limit = _calculate(_session(cpu_cores=4.0, cpu_request_cores=0.5))
    larger_limit = _calculate(_session(cpu_cores=16.0, cpu_request_cores=0.5))

    assert smaller_limit == larger_limit


def test_memory_request_mebibytes_are_converted_to_gibibytes_exactly():
    cost = _calculate(_session(memory_request_mb=384))

    assert cost.memory_gib_seconds == Decimal("3.750")


@pytest.mark.parametrize("vm_runtime", [False, True])
@pytest.mark.parametrize("burstable", [False, True])
def test_runtime_and_burstability_do_not_change_pricing(vm_runtime, burstable):
    expected = _calculate(_session(cpu_request_cores=0.5, memory_request_mb=1024))

    cost = _calculate(
        _session(
            vm_runtime=vm_runtime,
            burstable=burstable,
            cpu_request_cores=0.5,
            memory_request_mb=1024,
        )
    )

    assert cost == expected


def test_fractional_resources_and_cost_subtotals_remain_exact():
    cost = _calculate(
        _session(
            burstable=True,
            cpu_request_cores=0.125,
            memory_request_mb=384,
            ended_at=EFFECTIVE_AT + timedelta(seconds=3, microseconds=1),
        )
    )

    assert cost.cpu_core_seconds == Decimal("0.500")
    assert cost.memory_gib_seconds == Decimal("1.500")
    assert cost.cpu_cost_usd == Decimal("0.000005500")
    assert cost.memory_cost_usd == Decimal("0.0000031500")
    assert cost.total_cost_usd == cost.cpu_cost_usd + cost.memory_cost_usd
    assert cost.total_cost_usd == sum((line.total_cost_usd for line in cost.line_items), Decimal(0))


def test_rate_boundary_apportions_one_session_without_rounding_twice():
    session = _session(
        created_at=NEXT_RATE_AT - timedelta(hours=1),
        user_attributed_at=NEXT_RATE_AT - timedelta(microseconds=500_000),
        ended_at=NEXT_RATE_AT + timedelta(microseconds=500_000),
        ttl_expires_at=NEXT_RATE_AT + timedelta(hours=5),
    )

    cost = _calculate(session, NEXT_RATE_AT - timedelta(seconds=1), NEXT_RATE_AT + timedelta(seconds=1))

    assert cost.billable_seconds == 1
    assert len(cost.line_items) == 2
    assert cost.line_items[0].rate_card.version == RATE_V1.version
    assert cost.line_items[0].billable_seconds == Decimal("0.5")
    assert cost.line_items[1].billable_seconds == Decimal("0.5")


def test_rate_boundary_apportions_rounded_duration_proportionally():
    session = _session(
        created_at=NEXT_RATE_AT - timedelta(hours=1),
        user_attributed_at=NEXT_RATE_AT - timedelta(microseconds=900_000),
        ended_at=NEXT_RATE_AT + timedelta(microseconds=300_000),
        ttl_expires_at=NEXT_RATE_AT + timedelta(hours=5),
    )

    cost = _calculate(session, NEXT_RATE_AT - timedelta(seconds=1), NEXT_RATE_AT + timedelta(seconds=1))

    assert cost.billable_seconds == 2
    assert cost.line_items[0].rate_card.version == RATE_V1.version
    assert cost.line_items[0].billable_seconds == Decimal("1.5")
    assert cost.line_items[1].rate_card.version == RATE_V2.version
    assert cost.line_items[1].billable_seconds == Decimal("0.5")


def test_rounds_once_before_apportioning_across_reporting_periods():
    boundary = EFFECTIVE_AT + timedelta(hours=1)
    session = _session(
        user_attributed_at=boundary - timedelta(microseconds=600_000),
        ended_at=boundary + timedelta(microseconds=600_000),
    )

    first = _calculate(session, EFFECTIVE_AT, boundary)
    second = _calculate(session, boundary, EFFECTIVE_AT + timedelta(hours=2))

    assert first.billable_seconds == Decimal("1")
    assert second.billable_seconds == Decimal("1")
    assert first.billable_seconds + second.billable_seconds == Decimal("2")


def test_historical_window_keeps_old_rate_after_new_rate_is_active():
    historical = _session(
        created_at=NEXT_RATE_AT - timedelta(hours=1),
        user_attributed_at=NEXT_RATE_AT - timedelta(seconds=10),
        ended_at=NEXT_RATE_AT - timedelta(seconds=5),
        ttl_expires_at=NEXT_RATE_AT + timedelta(hours=5),
    )

    cost = _calculate(
        historical,
        NEXT_RATE_AT - timedelta(days=1),
        NEXT_RATE_AT,
        calculated_at=NEXT_RATE_AT + timedelta(days=30),
    )

    assert cost.line_items[0].rate_card == RATE_V1
    assert cost.cpu_cost_usd == cost.cpu_core_seconds * RATE_V1.cpu_core_second_usd


def test_usage_before_compute_billing_effective_date_is_not_priced():
    session = _session(
        user_attributed_at=EFFECTIVE_AT - timedelta(hours=1),
        ended_at=EFFECTIVE_AT - timedelta(seconds=1),
    )

    cost = _calculate(session, EFFECTIVE_AT - timedelta(days=1), EFFECTIVE_AT)

    assert cost.billable_seconds == 0
    assert cost.total_cost_usd == 0


@pytest.mark.parametrize(
    "cards, message",
    [
        ((), "at least one"),
        ((RATE_V1, RATE_V1), "versions"),
        (
            (
                RATE_V1,
                ComputeRateCard("overlap", NEXT_RATE_AT - timedelta(seconds=1), None, Decimal("1"), Decimal("1")),
            ),
            "overlap",
        ),
        (
            (
                RATE_V1,
                ComputeRateCard("gap", NEXT_RATE_AT + timedelta(seconds=1), None, Decimal("1"), Decimal("1")),
            ),
            "gaps",
        ),
    ],
)
def test_invalid_missing_overlapping_or_ambiguous_rate_cards_fail_safely(cards, message):
    with pytest.raises(ComputeRateCardConfigurationError, match=message):
        validate_compute_rate_cards(cards)


@pytest.mark.parametrize(
    "start,end,message",
    [
        (datetime(2026, 1, 1), EFFECTIVE_AT, "timezone-aware"),
        (EFFECTIVE_AT, datetime(2026, 1, 2), "timezone-aware"),
        (EFFECTIVE_AT, EFFECTIVE_AT, "must follow"),
        (EFFECTIVE_AT + timedelta(seconds=1), EFFECTIVE_AT, "must follow"),
    ],
)
def test_invalid_reporting_windows_are_rejected(start, end, message):
    with pytest.raises(ValueError, match=message):
        validate_reporting_window(start, end)


def test_reporting_window_accepts_different_aware_offsets():
    validate_reporting_window(EFFECTIVE_AT, EFFECTIVE_AT.astimezone(timezone(timedelta(hours=1))) + timedelta(1))
