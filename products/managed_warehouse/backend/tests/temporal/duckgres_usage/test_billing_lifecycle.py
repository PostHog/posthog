"""Lifecycle tests: duckgres responses → poll activity → mirror → usage-report gather.

The ONLY mock is the duckgres HTTP boundary (`fetch_usage` returning responses
shaped exactly as duckgres serves them: cumulative day rows whose values grow
across polls, stamps frozen at record time). Everything downstream is real —
the poll activity, team resolution, per-org mirror promotion, the cursor, the Team/
Organization tables, and the same gather queries the daily usage report runs
(`get_teams_with_managed_warehouse_compute_seconds_in_period`). These pin the
team-deletion / re-attribution / report-rerun behavior end to end, one process
short of a live duckgres (which the local E2E covers).

The billing-service half of the story — a re-sent report for the same date
OVERWRITES rather than adds (`UsageReport.objects.get_or_create` keyed on
customer/org/date) — lives in the billing repo's own API tests; here we assert
the property that makes that overwrite safe: every gather run restates the
FULL day (mirror rows are running totals), never a delta.
"""

import datetime as dt
import dataclasses
from decimal import Decimal

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db.models.signals import post_delete, pre_delete

from asgiref.sync import sync_to_async

from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async
from posthog.tasks.usage_report import get_teams_with_managed_warehouse_compute_seconds_in_period

from products.managed_warehouse.backend.models import DuckgresDailyStorageUsage, DuckgresDailyUsage
from products.managed_warehouse.backend.temporal.duckgres_usage.activities import poll_duckgres_usage
from products.managed_warehouse.backend.temporal.duckgres_usage.client import (
    StorageRow,
    UsageResponse,
    UsageRow,
    fetch_usage,
)
from products.managed_warehouse.backend.temporal.duckgres_usage.types import PollDuckgresUsageInputs

ORG = "018f0000-0000-0000-0000-000000000001"
DAY = dt.date(2026, 7, 6)
DAY_START = dt.datetime(2026, 7, 5, 23, 59, 59, tzinfo=dt.UTC)
DAY_END = dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def current_report_day():
    # These lifecycle tests model an in-progress July 6 billing day. Keep the
    # facade's notion of "today" aligned without freezing datetime globally:
    # lazy Django/Pydantic imports are not compatible with a replaced date type.
    with patch(
        "products.managed_warehouse.backend.facade.api.datetime",
        wraps=dt.datetime,
    ) as facade_datetime:
        facade_datetime.now.return_value = dt.datetime(2026, 7, 6, 12, tzinfo=dt.UTC)
        yield


def _row(team_id: int, cpu_seconds: int, date: dt.date = DAY) -> UsageRow:
    return UsageRow(
        date=date,
        org_id=ORG,
        team_id=team_id,
        query_source="standard",
        cpu=Decimal("8"),
        mem_gib=Decimal("16"),
        cpu_seconds=cpu_seconds,
        memory_seconds=0,  # keep the billable scalar == cpu_seconds for readable asserts
    )


def _response(rows: list[UsageRow], watermark_high: dt.datetime) -> UsageResponse:
    return UsageResponse(watermark_low=DAY_START, watermark_high=watermark_high, rows=rows)


async def _poll(response: UsageResponse, activity_environment):
    """Run the real poll activity with only the duckgres HTTP client mocked."""
    with (
        patch("products.managed_warehouse.backend.temporal.duckgres_usage.activities.is_configured", return_value=True),
        patch(
            "products.managed_warehouse.backend.temporal.duckgres_usage.activities.fetch_usage", return_value=response
        ),
        patch(
            "products.managed_warehouse.backend.temporal.duckgres_usage.activities.capture_exception"
        ) as mock_capture,
        patch(
            "products.managed_warehouse.backend.temporal.duckgres_usage.activities.logger", MagicMock(ainfo=AsyncMock())
        ),
    ):
        result = await activity_environment.run(poll_duckgres_usage, PollDuckgresUsageInputs())
    return result, mock_capture


@sync_to_async
def _gather_day() -> dict[int, int]:
    """What the daily usage report's gather sees for DAY: {team_id: billable total}."""
    begin = dt.datetime.combine(DAY, dt.time.min, tzinfo=dt.UTC)
    end = dt.datetime.combine(DAY, dt.time.max, tzinfo=dt.UTC)
    rows = get_teams_with_managed_warehouse_compute_seconds_in_period(begin, end)
    return {r["team_id"]: r["total"] for r in rows}


mirror_rows = sync_to_async(lambda: sorted(DuckgresDailyUsage.objects.values_list("team_id", "cpu_seconds")))
mirror_rows_with_org = sync_to_async(
    lambda: sorted(
        (str(org_id), team_id, total)
        for org_id, team_id, total in DuckgresDailyUsage.objects.values_list(
            "organization_id", "team_id", "cpu_seconds"
        )
    )
)


@sync_to_async
def _make_org_with_teams(*team_ids: int) -> None:
    org = Organization.objects.create(id=ORG, name="mdw lifecycle org")
    for tid in team_ids:
        Team.objects.create(id=tid, organization=org, name=f"team-{tid}")


@database_sync_to_async
def delete_team(team_id: int) -> None:
    # The scenario begins after deletion has committed; deletion-hook behavior is
    # deliberately out of scope. Keep ORM cascades, but avoid unrelated cache hooks.
    with patch.object(pre_delete, "send"), patch.object(post_delete, "send"):
        Team.objects.get(id=team_id).delete()


async def test_report_rerun_after_deletion_and_remap_restates_not_doubles(activity_environment) -> None:
    """Roy's timeline: mid-day report under X, X deleted, remap to Y, day grows,
    second report run. Each gather run must be a full restatement of the day
    (that's what makes billing's same-date overwrite correct), and the final
    total must be the real usage — never first-run + second-run."""
    await _make_org_with_teams(101, 102)  # X=102, Y=101 (lowest id → the surrogate)

    # Poll 1: mid-day, X has accrued 100.
    result, _ = await _poll(
        _response([_row(102, 100)], dt.datetime(2026, 7, 6, 12, 0, tzinfo=dt.UTC)), activity_environment
    )
    assert result.rows_written == 1

    # "Usage report run 1" carries X's usage.
    run1 = await _gather_day()
    assert run1 == {102: 100}

    # Team X is deleted; duckgres keeps serving the bucket with the frozen stamp,
    # value grown to 150 (the bucket is cumulative — NOT a 50 delta).
    await delete_team(102)
    result, _ = await _poll(
        _response([_row(102, 150)], dt.datetime(2026, 7, 6, 18, 0, tzinfo=dt.UTC)), activity_environment
    )

    # The mirror holds exactly ONE row for the day: remapped to Y, value replaced.
    assert await mirror_rows() == [(101, 150)]

    # "Usage report run 2": a full restatement under Y — 150, not 250, X gone.
    run2 = await _gather_day()
    assert run2 == {101: 150}
    assert sum(run2.values()) == 150  # the org-level number billing would overwrite with

    # Org-total invariance across the remap: run 2 is a superset restatement of
    # run 1 (same org, same date) — billing's per-date overwrite lands on 150.
    assert sum(run2.values()) >= sum(run1.values())


async def test_mid_day_deletion_splits_day_without_loss_or_double(activity_environment) -> None:
    """Pre-deletion accrual arrives dead-stamped, post-deletion accrual arrives
    live-stamped (duckgres's team list synced). The day bills fully, once."""
    await _make_org_with_teams(201, 202)  # X=202 (to delete), Y=201

    await delete_team(202)
    # One pull sees both halves: X's frozen pre-deletion bucket + Y's native bucket.
    result, _ = await _poll(
        _response([_row(202, 100), _row(201, 50)], dt.datetime(2026, 7, 6, 18, 0, tzinfo=dt.UTC)),
        activity_environment,
    )

    # X's half folds onto Y (same billing key after remap) — one row, summed once.
    assert await mirror_rows() == [(201, 150)]
    assert (await _gather_day()) == {201: 150}


async def test_reserved_growing_buckets_converge_without_accumulating(activity_environment) -> None:
    """duckgres re-serves the same cumulative bucket every poll with a grown
    value; promotion must keep exactly one row at the latest value —
    across a deletion mid-sequence — never sum the re-serves."""
    await _make_org_with_teams(301, 302)

    for hour, value in ((10, 40), (12, 90)):
        await _poll(
            _response([_row(302, value)], dt.datetime(2026, 7, 6, hour, 0, tzinfo=dt.UTC)), activity_environment
        )
    assert await mirror_rows() == [(302, 90)]

    await delete_team(302)
    for hour, value in ((14, 120), (16, 150)):
        await _poll(
            _response([_row(302, value)], dt.datetime(2026, 7, 6, hour, 0, tzinfo=dt.UTC)), activity_environment
        )

    # Still one row; remap is deterministic (same surrogate each poll), value replaced.
    assert await mirror_rows() == [(301, 150)]
    assert (await _gather_day()) == {301: 150}


async def test_closed_day_acks_once_and_late_reserve_is_absorbed(activity_environment) -> None:
    """The custody handoff around the remap: the day closes → ack offered; a
    duckgres-behind re-serve of the same window after the ack must be absorbed
    idempotently (replace), not double-persisted, and must not regress the cursor."""
    await _make_org_with_teams(401, 402)
    await delete_team(402)

    closed = _response([_row(402, 100)], dt.datetime(2026, 7, 7, 0, 5, tzinfo=dt.UTC))
    result, _ = await _poll(closed, activity_environment)
    assert result.ack_watermark == DAY_END.isoformat()  # day closed → ack offered

    # duckgres re-serves the identical window (e.g. our ack POST never landed).
    result, _ = await _poll(closed, activity_environment)
    assert await mirror_rows() == [(401, 100)]  # absorbed, not doubled
    assert result.ack_watermark == DAY_END.isoformat()  # re-offered, idempotent
    assert (await _gather_day()) == {401: 100}


async def test_orphan_org_never_reaches_the_gather(activity_environment) -> None:
    await database_sync_to_async(Organization.objects.create)(id=ORG, name="orphan org")  # no teams

    result, mock_capture = await _poll(
        _response([_row(999, 100)], dt.datetime(2026, 7, 7, 0, 5, tzinfo=dt.UTC)), activity_environment
    )

    assert await mirror_rows() == [(999, 100)]
    assert (await _gather_day()) == {}  # nothing for any report run to bill
    mock_capture.assert_called_once()  # DuckgresUsageOrphanedOrg — loud
    assert result.ack_watermark == DAY_END.isoformat()  # ack still proceeds
    assert result.orphaned_org_ids == [ORG]


async def test_team_deleted_after_ack_is_reattributed_by_the_gather(activity_environment) -> None:
    await _make_org_with_teams(91, 92)

    result, _ = await _poll(
        _response([_row(92, 100)], dt.datetime(2026, 7, 7, 0, 5, tzinfo=dt.UTC)), activity_environment
    )
    assert result.ack_watermark == DAY_END.isoformat()
    assert await mirror_rows() == [(92, 100)]

    await delete_team(92)

    assert (await _gather_day()) == {91: 100}
    assert await mirror_rows() == [(92, 100)]


ORG_B = "018f0000-0000-0000-0000-000000000002"


async def test_cross_org_zero_stamps_never_collide_in_the_mirror(activity_environment) -> None:
    """The same sentinel team stamp is safe because mirror identity includes org."""
    await _make_org_with_teams(501)
    org_b = await database_sync_to_async(Organization.objects.create)(id=ORG_B, name="org b")
    await database_sync_to_async(Team.objects.create)(id=502, organization=org_b, name="team-502")

    row_b = dataclasses.replace(_row(0, 70), org_id=ORG_B)
    result, _ = await _poll(
        _response([_row(0, 30), row_b], dt.datetime(2026, 7, 6, 18, 0, tzinfo=dt.UTC)), activity_environment
    )

    # Each org's 0-stamp lands on its OWN billable team — two rows, no collision.
    assert result.rows_written == 2
    assert await mirror_rows() == [(501, 30), (502, 70)]
    assert await mirror_rows_with_org() == [(ORG, 501, 30), (ORG_B, 502, 70)]


async def test_cross_org_unresolved_zero_stamps_are_both_retained(activity_environment) -> None:
    await database_sync_to_async(Organization.objects.create)(id=ORG, name="org a")
    await database_sync_to_async(Organization.objects.create)(id=ORG_B, name="org b")

    row_b = dataclasses.replace(_row(0, 70), org_id=ORG_B)
    result, _ = await _poll(
        _response([_row(0, 30), row_b], dt.datetime(2026, 7, 6, 18, 0, tzinfo=dt.UTC)), activity_environment
    )

    assert result.rows_written == 2
    assert await mirror_rows_with_org() == [(ORG, 0, 30), (ORG_B, 0, 70)]


async def test_surrogate_deletion_cascades_and_still_converges(activity_environment) -> None:
    """The elected surrogate itself gets deleted mid-window: the next poll must
    re-elect the next billable team, replace (not duplicate) the mirror row, and
    keep the org total constant."""
    await _make_org_with_teams(601, 602)  # surrogate order: 601 first, then 602

    await delete_team(601)  # the would-be surrogate is gone before any usage arrives
    result, _ = await _poll(
        _response([_row(999, 100)], dt.datetime(2026, 7, 6, 12, 0, tzinfo=dt.UTC)), activity_environment
    )
    assert await mirror_rows() == [(602, 100)]  # dead stamp elected onto the surviving team

    # Recreate a lower-id billable team mid-window: the deterministic election
    # (lowest id) now picks it — replace_window must swap the row, not add one.
    org = await database_sync_to_async(Organization.objects.get)(id=ORG)
    await database_sync_to_async(Team.objects.create)(id=600, organization=org, name="team-600")
    result, _ = await _poll(
        _response([_row(999, 150)], dt.datetime(2026, 7, 6, 18, 0, tzinfo=dt.UTC)), activity_environment
    )

    assert await mirror_rows() == [(600, 150)]  # one row, re-elected, value replaced
    assert (await _gather_day()) == {600: 150}  # org total unchanged by the election move


async def test_storage_family_remaps_and_bills_exact_decimal_gb_hours(activity_environment) -> None:
    """The storage family through the same lifecycle: a dead-stamped GiB-seconds
    row remaps and the REAL storage gather converts it to billable decimal-GB
    hours exactly (the binary→decimal step is a ~7.4% billing error if wrong)."""
    from posthog.tasks.usage_report import get_teams_with_managed_warehouse_storage_gb_hours_in_period

    from products.managed_warehouse.backend.temporal.duckgres_usage.client import StorageRow

    await _make_org_with_teams(701)

    # 100 decimal-GB hours exactly: byte_seconds = 100 * 10^9 * 3600, served by
    # duckgres as GiB-seconds (byte_seconds / 2^30) — a 15-digit exact decimal.
    byte_seconds = 100 * 10**9 * 3600
    gib_seconds = Decimal(byte_seconds) / Decimal(2**30)
    storage = StorageRow(date=DAY, org_id=ORG, team_id=999, gib_seconds=gib_seconds)
    response = UsageResponse(
        watermark_low=DAY_START,
        watermark_high=dt.datetime(2026, 7, 6, 18, 0, tzinfo=dt.UTC),
        rows=[],
        storage_rows=[storage],
    )
    await _poll(response, activity_environment)

    def gather_storage() -> dict[int, int]:
        begin = dt.datetime.combine(DAY, dt.time.min, tzinfo=dt.UTC)
        end = dt.datetime.combine(DAY, dt.time.max, tzinfo=dt.UTC)
        return {
            r["team_id"]: r["total"] for r in get_teams_with_managed_warehouse_storage_gb_hours_in_period(begin, end)
        }

    assert (await sync_to_async(gather_storage)()) == {701: 100}  # remapped AND exact


async def test_conflicting_rows_retain_the_last_good_value_while_ack_is_withheld(activity_environment) -> None:
    await _make_org_with_teams(801)
    await _poll(_response([_row(801, 100)], dt.datetime(2026, 7, 6, 12, 0, tzinfo=dt.UTC)), activity_environment)

    result, mock_capture = await _poll(
        _response([_row(801, 90), _row(801, 250)], dt.datetime(2026, 7, 6, 18, 0, tzinfo=dt.UTC)),
        activity_environment,
    )

    assert await mirror_rows() == [(801, 100)]
    assert (await _gather_day()) == {801: 100}
    assert result.ack_watermark is None  # duckgres keeps the source for reconciliation
    mock_capture.assert_called_once()  # DuckgresConflictingRows


async def test_malformed_org_id_is_quarantined_not_fatal(activity_environment) -> None:
    """A non-UUID org_id (duckgres contract break — the dev seed's org is
    literally named 'local') must not crash the poll: the row is dropped and
    alerted, every other org still lands, and the ack proceeds — a bucket's
    org_id never changes, so withholding would freeze the ack forever."""
    await _make_org_with_teams(901)

    bad = dataclasses.replace(_row(999, 100), org_id="local")
    closed = dt.datetime(2026, 7, 7, 0, 5, tzinfo=dt.UTC)  # day closed -> ack on offer
    result, mock_capture = await _poll(_response([_row(901, 50), bad], closed), activity_environment)

    assert await mirror_rows() == [(901, 50)]  # the good org still lands
    assert result.malformed_org_row_count == 1
    mock_capture.assert_called_once()  # DuckgresMalformedOrgRows — loud
    assert result.ack_watermark == DAY_END.isoformat()  # ack NOT withheld


async def test_multi_day_downtime_catches_up_in_one_poll_and_one_ack(activity_environment) -> None:
    """The claimed advantage of day-aggregation + replace: billing downtime
    can't create backlog. One poll restores every missed day (bounded: one row
    per key per day), the remap works across all of them, per-day gather totals
    are exact, and a single ack seals everything through the last closed day."""
    await _make_org_with_teams(1001, 1002)
    await delete_team(1002)  # day 4's usage is stranded on a dead stamp

    response = UsageResponse(
        watermark_low=dt.datetime(2026, 7, 3, 23, 59, 59, tzinfo=dt.UTC),  # 3 days behind
        watermark_high=dt.datetime(2026, 7, 7, 0, 5, tzinfo=dt.UTC),
        rows=[
            _row(1002, 100, date=dt.date(2026, 7, 4)),  # dead-stamped, mid-window
            _row(1001, 200, date=dt.date(2026, 7, 5)),
            _row(1001, 300, date=dt.date(2026, 7, 6)),
            _row(1001, 10, date=dt.date(2026, 7, 7)),  # the open day
        ],
    )
    result, _ = await _poll(response, activity_environment)

    assert result.rows_written == 4  # the whole outage restored in one pull
    assert result.ack_watermark == DAY_END.isoformat()  # one ack seals days 4-6

    def gather_on(day: dt.date) -> dict[int, int]:
        begin = dt.datetime.combine(day, dt.time.min, tzinfo=dt.UTC)
        end = dt.datetime.combine(day, dt.time.max, tzinfo=dt.UTC)
        rows = get_teams_with_managed_warehouse_compute_seconds_in_period(begin, end)
        return {r["team_id"]: r["total"] for r in rows}

    gather = sync_to_async(lambda: [gather_on(dt.date(2026, 7, d)) for d in (4, 5, 6, 7)])
    assert await gather() == [{1001: 100}, {1001: 200}, {1001: 300}, {1001: 10}]


async def test_endpoints_and_standard_products_stay_separate_through_the_remap(activity_environment) -> None:
    """Two products bill off one mirror table, split by query_source. A dead
    stamp carrying BOTH sources must remap into two separate rows (the fold key
    includes the source), and each product's gather must see only its own —
    a cross-product leak would bill compute usage as endpoints or vice versa."""
    from posthog.tasks.usage_report import get_teams_with_managed_warehouse_endpoints_compute_seconds_in_period

    await _make_org_with_teams(1101)

    endpoints_row = dataclasses.replace(_row(999, 40), query_source="endpoints")
    result, _ = await _poll(
        _response([_row(999, 100), endpoints_row], dt.datetime(2026, 7, 6, 18, 0, tzinfo=dt.UTC)),
        activity_environment,
    )
    assert result.rows_written == 2  # same dead stamp, same surrogate — two rows, not folded

    def gather_both() -> tuple[dict[int, int], dict[int, int]]:
        begin = dt.datetime.combine(DAY, dt.time.min, tzinfo=dt.UTC)
        end = dt.datetime.combine(DAY, dt.time.max, tzinfo=dt.UTC)
        standard = {
            r["team_id"]: r["total"] for r in get_teams_with_managed_warehouse_compute_seconds_in_period(begin, end)
        }
        endpoints = {
            r["team_id"]: r["total"]
            for r in get_teams_with_managed_warehouse_endpoints_compute_seconds_in_period(begin, end)
        }
        return standard, endpoints

    standard, endpoints = await sync_to_async(gather_both)()
    assert standard == {1101: 100}  # compute product: only the standard row
    assert endpoints == {1101: 40}  # endpoints product: only the endpoints row


async def test_shrinking_reserve_is_surfaced_not_silently_accepted(activity_environment) -> None:
    await _make_org_with_teams(1201)

    await _poll(_response([_row(1201, 150)], dt.datetime(2026, 7, 6, 12, 0, tzinfo=dt.UTC)), activity_environment)
    result, mock_capture = await _poll(
        _response([_row(1201, 90)], dt.datetime(2026, 7, 6, 12, 10, tzinfo=dt.UTC)), activity_environment
    )

    assert await mirror_rows() == [(1201, 150)]  # keep the larger, like a conflict
    mock_capture.assert_called_once()  # and say so


async def test_permanently_invalid_replacement_does_not_turn_into_a_recoverable_regression(
    activity_environment,
) -> None:
    await _make_org_with_teams(1251)
    await _poll(_response([_row(1251, 150)], dt.datetime(2026, 7, 6, 12, 0, tzinfo=dt.UTC)), activity_environment)

    with patch(
        "products.managed_warehouse.backend.temporal.duckgres_usage.client._request",
        return_value={
            "watermark_low": DAY_START.isoformat(),
            "watermark_high": "2026-07-07T00:05:00+00:00",
            "usage": [
                {
                    "date": DAY.isoformat(),
                    "org_id": ORG,
                    "team_id": 1251,
                    "query_source": "standard",
                    "cpu": "8",
                    "mem_gib": "16",
                    "cpu_seconds": -1,
                    "memory_seconds": 0,
                }
            ],
            "storage": [],
        },
    ):
        invalid_response = fetch_usage()

    result, mock_capture = await _poll(invalid_response, activity_environment)

    assert await mirror_rows() == [(1251, 150)]
    assert result.ack_watermark == DAY_END.isoformat()
    assert [type(call.args[0]).__name__ for call in mock_capture.call_args_list] == ["DuckgresInvalidValueRows"]


async def test_permanently_invalid_storage_does_not_turn_into_a_recoverable_regression(
    activity_environment,
) -> None:
    await _make_org_with_teams(1252)
    await _poll(
        UsageResponse(
            watermark_low=DAY_START,
            watermark_high=dt.datetime(2026, 7, 6, 12, 0, tzinfo=dt.UTC),
            rows=[],
            storage_rows=[StorageRow(date=DAY, org_id=ORG, team_id=1252, gib_seconds=Decimal("150"))],
        ),
        activity_environment,
    )

    with patch(
        "products.managed_warehouse.backend.temporal.duckgres_usage.client._request",
        return_value={
            "watermark_low": DAY_START.isoformat(),
            "watermark_high": "2026-07-07T00:05:00+00:00",
            "usage": [],
            "storage": [
                {
                    "date": DAY.isoformat(),
                    "org_id": ORG,
                    "team_id": 1252,
                    "gib_seconds": -1,
                }
            ],
        },
    ):
        invalid_response = fetch_usage()

    result, mock_capture = await _poll(invalid_response, activity_environment)

    stored = sync_to_async(lambda: DuckgresDailyStorageUsage.objects.get().gib_seconds)
    assert await stored() == Decimal("150")
    assert result.ack_watermark == DAY_END.isoformat()
    assert [type(call.args[0]).__name__ for call in mock_capture.call_args_list] == ["DuckgresInvalidValueRows"]


async def test_invalid_product_retains_last_good_while_valid_product_advances(activity_environment) -> None:
    await _make_org_with_teams(1253)
    endpoints = dataclasses.replace(_row(1253, 40), query_source="endpoints")
    await _poll(
        _response([_row(1253, 150), endpoints], dt.datetime(2026, 7, 6, 12, 0, tzinfo=dt.UTC)),
        activity_environment,
    )

    with patch(
        "products.managed_warehouse.backend.temporal.duckgres_usage.client._request",
        return_value={
            "watermark_low": DAY_START.isoformat(),
            "watermark_high": "2026-07-07T00:05:00+00:00",
            "usage": [
                {
                    "date": DAY.isoformat(),
                    "org_id": ORG,
                    "team_id": 1253,
                    "query_source": "standard",
                    "cpu": "8",
                    "mem_gib": "16",
                    "cpu_seconds": 250,
                    "memory_seconds": 0,
                },
                {
                    "date": DAY.isoformat(),
                    "org_id": ORG,
                    "team_id": 1253,
                    "query_source": "endpoints",
                    "cpu": "8",
                    "mem_gib": "16",
                    "cpu_seconds": -1,
                    "memory_seconds": 0,
                },
            ],
            "storage": [],
        },
    ):
        mixed_response = fetch_usage()

    result, mock_capture = await _poll(mixed_response, activity_environment)

    stored = sync_to_async(lambda: sorted(DuckgresDailyUsage.objects.values_list("query_source", "cpu_seconds")))
    assert await stored() == [("endpoints", 40), ("standard", 250)]
    assert result.ack_watermark == DAY_END.isoformat()
    assert [type(call.args[0]).__name__ for call in mock_capture.call_args_list] == ["DuckgresInvalidValueRows"]


async def test_conflicting_foreign_rows_do_not_withhold_ack(activity_environment) -> None:
    await _make_org_with_teams(1261)
    foreign_org = await database_sync_to_async(Organization.objects.create)(id=ORG_B, name="foreign org")
    await database_sync_to_async(Team.objects.create)(id=1262, organization=foreign_org, name="foreign team")

    result, mock_capture = await _poll(
        _response(
            [_row(1262, 100), _row(1262, 150)],
            dt.datetime(2026, 7, 7, 0, 5, tzinfo=dt.UTC),
        ),
        activity_environment,
    )

    assert await mirror_rows() == []
    assert result.ack_watermark == DAY_END.isoformat()
    assert [type(call.args[0]).__name__ for call in mock_capture.call_args_list] == ["DuckgresForeignTeamRows"]


async def test_regressed_orgs_keep_last_good_while_a_healthy_org_advances(activity_environment) -> None:
    await _make_org_with_teams(1301)
    org_b = await database_sync_to_async(Organization.objects.create)(id=ORG_B, name="org b")
    await database_sync_to_async(Team.objects.create)(id=1302, organization=org_b, name="team-1302")
    org_c_id = "018f0000-0000-0000-0000-000000000003"
    org_c = await database_sync_to_async(Organization.objects.create)(id=org_c_id, name="org c")
    await database_sync_to_async(Team.objects.create)(id=1303, organization=org_c, name="team-1303")

    row_b = dataclasses.replace(_row(1302, 80), org_id=ORG_B)
    row_c = dataclasses.replace(_row(1303, 100), org_id=org_c_id)
    await _poll(
        _response([_row(1301, 150), row_b, row_c], dt.datetime(2026, 7, 6, 23, 50, tzinfo=dt.UTC)),
        activity_environment,
    )

    regressed_a = _row(1301, 90)
    advanced_c = dataclasses.replace(_row(1303, 200), org_id=org_c_id)
    result, mock_capture = await _poll(
        _response([regressed_a, advanced_c], dt.datetime(2026, 7, 7, 0, 5, tzinfo=dt.UTC)),
        activity_environment,
    )

    assert await mirror_rows_with_org() == [(ORG, 1301, 150), (ORG_B, 1302, 80), (org_c_id, 1303, 200)]
    assert result.rows_written == 1
    assert result.ack_watermark is None
    captured = [type(call.args[0]).__name__ for call in mock_capture.call_args_list]
    assert captured == ["DuckgresUsageRegression"]
