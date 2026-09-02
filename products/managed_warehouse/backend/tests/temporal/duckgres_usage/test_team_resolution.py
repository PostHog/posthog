"""Tests for re-attributing usage rows whose team has been deleted.

duckgres stamps buckets with an informational team hint (the connecting user's
team, else the org's oldest team, else 0) and never re-attributes on its side,
so rows can arrive under a deleted team's id or 0 — and those would be dropped
by the (live-teams-only) usage-report gather. resolve_billing_teams remaps them
to a live team in the same org so the org still bills — org-level attribution
makes the surrogate choice billing-neutral. Orgs with no billable team at all
are orphan orgs (rows retained, surfaced via orphaned_org_ids, ack proceeds).
"""

import datetime as dt
from decimal import Decimal

import pytest

from posthog.models import Organization, Team

from products.managed_warehouse.backend.temporal.duckgres_usage.client import StorageRow, UsageRow
from products.managed_warehouse.backend.temporal.duckgres_usage.team_resolution import resolve_billing_teams

pytestmark = pytest.mark.django_db

DEAD = 88_888_888  # an id no Team has
DEAD_2 = 88_888_889


def _org_with_teams(n: int = 2) -> tuple[Organization, list[Team]]:
    org = Organization.objects.create(name="mdw org")
    teams = [Team.objects.create(organization=org, name=f"team-{i}") for i in range(n)]
    return org, teams


def _compute(
    team_id: int,
    org_id: str,
    *,
    date: dt.date = dt.date(2026, 7, 6),
    cpu_seconds: int = 100,
    memory_seconds: int = 800,
    query_source: str = "standard",
) -> UsageRow:
    return UsageRow(
        date=date,
        org_id=org_id,
        team_id=team_id,
        query_source=query_source,
        cpu=Decimal("8"),
        mem_gib=Decimal("16"),
        cpu_seconds=cpu_seconds,
        memory_seconds=memory_seconds,
    )


def _storage(team_id: int, org_id: str, *, date: dt.date = dt.date(2026, 7, 6), gib: str = "360000") -> StorageRow:
    return StorageRow(date=date, org_id=org_id, team_id=team_id, gib_seconds=Decimal(gib))


def test_live_team_rows_pass_through_untouched() -> None:
    org, (t0, t1) = _org_with_teams()
    compute = [_compute(t0.id, str(org.id))]
    storage = [_storage(t1.id, str(org.id))]

    result = resolve_billing_teams(compute, storage)

    assert result.compute_rows == compute
    assert result.storage_rows == storage
    assert result.orphaned_org_ids == set()


def test_deleted_team_remapped_to_lowest_live_team_in_org() -> None:
    org, (t0, t1) = _org_with_teams()
    lowest = min(t0.id, t1.id)

    result = resolve_billing_teams(
        [_compute(DEAD, str(org.id), cpu_seconds=100)],
        [_storage(DEAD, str(org.id), gib="500")],
    )

    assert [r.team_id for r in result.compute_rows] == [lowest]
    assert [r.team_id for r in result.storage_rows] == [lowest]
    assert result.compute_rows[0].cpu_seconds == 100  # the value rides along unchanged
    assert result.storage_rows[0].gib_seconds == Decimal("500")
    assert result.orphaned_org_ids == set()


def test_org_with_no_live_team_is_retained_and_reported() -> None:
    org = Organization.objects.create(name="no projects")  # warehouse but zero teams

    result = resolve_billing_teams([_compute(DEAD, str(org.id))], [_storage(DEAD, str(org.id))])

    assert result.compute_rows == [_compute(DEAD, str(org.id))]
    assert result.storage_rows == [_storage(DEAD, str(org.id))]
    assert result.orphaned_org_ids == {str(org.id)}


def test_two_dead_teams_in_one_org_fold_onto_the_surrogate() -> None:
    org, (t0, t1) = _org_with_teams()
    lowest = min(t0.id, t1.id)
    # Two distinct dead teams at the same billing key — must sum, not collide.
    compute = [
        _compute(DEAD, str(org.id), cpu_seconds=100, memory_seconds=80),
        _compute(DEAD_2, str(org.id), cpu_seconds=50, memory_seconds=40),
    ]

    result = resolve_billing_teams(compute, [])

    assert len(result.compute_rows) == 1
    assert result.compute_rows[0].team_id == lowest
    assert result.compute_rows[0].cpu_seconds == 150
    assert result.compute_rows[0].memory_seconds == 120


def test_only_the_dead_org_is_reattributed_not_its_live_sibling() -> None:
    org_a, (a0, a1) = _org_with_teams()
    org_b, (b0,) = _org_with_teams(n=1)
    compute = [
        _compute(a0.id, str(org_a.id)),  # live in A -> untouched
        _compute(DEAD, str(org_a.id), date=dt.date(2026, 7, 7)),  # dead in A -> A's lowest
        _compute(DEAD, str(org_b.id)),  # dead in B -> B's only team
    ]

    result = resolve_billing_teams(compute, [])

    by_org = {(r.org_id, r.date): r.team_id for r in result.compute_rows}
    assert by_org[(str(org_a.id), dt.date(2026, 7, 6))] == a0.id
    assert by_org[(str(org_a.id), dt.date(2026, 7, 7))] == min(a0.id, a1.id)
    assert by_org[(str(org_b.id), dt.date(2026, 7, 6))] == b0.id
    assert result.orphaned_org_ids == set()


def test_empty_input_is_a_noop() -> None:
    result = resolve_billing_teams([], [])
    assert result.compute_rows == []
    assert result.storage_rows == []
    assert result.orphaned_org_ids == set()


# --- the team_id=0 sentinel ----------------------------------------------------
# duckgres stamps 0 when it knows no team for the connection (its "no team
# known" fallback — team attribution is ours, not its). 0 is never a real Team
# id, so it rides the deleted-team path: remap when the org has a billable
# team, flag the org as an orphan when it doesn't.


def test_zero_stamped_rows_remap_to_lowest_billable_team() -> None:
    org, (t0, t1) = _org_with_teams()
    lowest = min(t0.id, t1.id)

    result = resolve_billing_teams([_compute(0, str(org.id))], [_storage(0, str(org.id))])

    assert [r.team_id for r in result.compute_rows] == [lowest]
    assert [r.team_id for r in result.storage_rows] == [lowest]
    assert result.orphaned_org_ids == set()


def test_zero_stamped_rows_with_no_billable_team_are_orphaned() -> None:
    org = Organization.objects.create(name="no projects")

    result = resolve_billing_teams([_compute(0, str(org.id))], [_storage(0, str(org.id))])

    assert [row.team_id for row in result.compute_rows] == [0]
    assert [row.team_id for row in result.storage_rows] == [0]
    assert result.orphaned_org_ids == {str(org.id)}


# --- "live team" must equal the usage gather's "billable team" -----------------
# The gather (_get_teams_for_usage_reports) excludes demo projects and
# internal-metrics orgs. The resolver must use the same definition — otherwise it
# elects a team the gather will never bill, silently under-billing the org.

DEMO = 88_800_001  # a demo team, low id (would be picked first by a naive election)
REAL = 88_800_002  # the real billable team, higher id


def test_demo_team_is_not_elected_as_surrogate() -> None:
    org = Organization.objects.create(name="mdw org")
    Team.objects.create(id=DEMO, organization=org, name="demo", is_demo=True)  # lowest id, NOT billable
    real = Team.objects.create(id=REAL, organization=org, name="real")

    result = resolve_billing_teams([_compute(DEAD, str(org.id))], [])

    assert [r.team_id for r in result.compute_rows] == [real.id]  # skips the lower-id demo team


def test_org_with_only_a_demo_team_is_orphaned() -> None:
    org = Organization.objects.create(name="demo only")
    Team.objects.create(id=DEMO, organization=org, name="demo", is_demo=True)  # the only "live" team

    result = resolve_billing_teams([_compute(DEAD, str(org.id))], [])

    assert result.orphaned_org_ids == {str(org.id)}  # loud + safe, not silently onto the demo team
    assert [row.team_id for row in result.compute_rows] == [DEAD]


def test_internal_metrics_org_is_orphaned() -> None:
    org = Organization.objects.create(name="internal", for_internal_metrics=True)
    Team.objects.create(id=88_800_003, organization=org, name="internal team")

    result = resolve_billing_teams([_compute(DEAD, str(org.id))], [])

    assert result.orphaned_org_ids == {str(org.id)}  # internal orgs are unbilled by design


def test_live_demo_stamped_rows_are_left_untouched() -> None:
    # duckgres stamped usage with a LIVE demo team that shares the org with a real
    # team. The demo team is intentionally non-billable but *exists* — remapping its
    # usage onto the real team would bill what the gather deliberately excludes.
    # Only *deleted* (or 0-stamped) teams get moved.
    org = Organization.objects.create(name="demo stamped")
    Team.objects.create(id=DEMO, organization=org, name="demo", is_demo=True)
    Team.objects.create(id=REAL, organization=org, name="real")

    result = resolve_billing_teams([_compute(DEMO, str(org.id))], [])

    assert [r.team_id for r in result.compute_rows] == [DEMO]  # left under the demo team, not remapped
    assert result.orphaned_org_ids == set()  # kept, not dropped


def test_live_internal_org_team_rows_are_left_untouched() -> None:
    # A live team in a for_internal_metrics org — unbilled by design, but it exists.
    # Its rows stay put (the gather excludes them anyway); not remapped, and the org is
    # not "orphaned" — nothing was deleted.
    org = Organization.objects.create(name="internal", for_internal_metrics=True)
    internal_team = Team.objects.create(id=88_800_009, organization=org, name="internal")
    Team.objects.create(id=88_800_010, organization=org, name="internal 2")

    result = resolve_billing_teams([_compute(internal_team.id, str(org.id))], [])

    assert [r.team_id for r in result.compute_rows] == [internal_team.id]  # left alone
    assert result.orphaned_org_ids == set()  # not deleted → not orphaned


def test_raw_duplicate_rows_are_deduped_not_summed() -> None:
    org, (t0, _) = _org_with_teams()
    # duckgres emits the same billing key twice (a contract violation). Summing them
    # in the fold would double-bill, so keep one and surface the drop.
    row = _compute(t0.id, str(org.id), cpu_seconds=100)
    result = resolve_billing_teams([row, row], [])

    assert len(result.compute_rows) == 1
    assert result.compute_rows[0].cpu_seconds == 100  # kept one — NOT summed to 200
    assert result.duplicate_row_count == 1


def test_reattribution_collision_still_sums_not_deduped() -> None:
    # Two *distinct* dead teams folded onto one surrogate is a legit merge — still summed,
    # not mistaken for a duplicate.
    org, (t0, _) = _org_with_teams()
    result = resolve_billing_teams(
        [_compute(DEAD, str(org.id), cpu_seconds=100), _compute(DEAD_2, str(org.id), cpu_seconds=50)], []
    )

    assert len(result.compute_rows) == 1
    assert result.compute_rows[0].cpu_seconds == 150  # summed
    assert result.duplicate_row_count == 0  # not a raw duplicate


def test_same_key_conflicting_values_keep_max_and_flag() -> None:
    # Same key, DIFFERENT measures (a partial then a corrected total) — we can't tell
    # which is right, so keep the larger (err high) and flag it as a *conflict*,
    # distinct from a harmless exact duplicate.
    org, (t0, _) = _org_with_teams()
    smaller = _compute(t0.id, str(org.id), cpu_seconds=100)
    larger = _compute(t0.id, str(org.id), cpu_seconds=250)

    result = resolve_billing_teams([smaller, larger], [])

    assert len(result.compute_rows) == 1
    assert result.compute_rows[0].cpu_seconds == 250  # kept the max, not the first
    assert result.conflicting_row_count == 1
    assert result.conflicting_org_ids == {str(org.id)}
    assert result.duplicate_row_count == 0


def test_conflicting_values_keep_max_when_larger_comes_first() -> None:
    # keep-max must not depend on order: when the larger row arrives first, the smaller
    # one that follows must NOT overwrite it (exercises the "don't replace" else-branch).
    org, (t0, _) = _org_with_teams()
    larger = _compute(t0.id, str(org.id), cpu_seconds=250)
    smaller = _compute(t0.id, str(org.id), cpu_seconds=100)

    result = resolve_billing_teams([larger, smaller], [])

    assert len(result.compute_rows) == 1
    assert result.compute_rows[0].cpu_seconds == 250  # kept the max even though it came first
    assert result.conflicting_row_count == 1
    assert result.conflicting_org_ids == {str(org.id)}


def test_storage_exact_duplicate_is_deduped() -> None:
    org, (t0, _) = _org_with_teams()
    row = _storage(t0.id, str(org.id), gib="360000")

    result = resolve_billing_teams([], [row, row])

    assert len(result.storage_rows) == 1
    assert result.duplicate_row_count == 1
    assert result.conflicting_row_count == 0


def test_storage_conflicting_values_keep_max_and_flag() -> None:
    org, (t0, _) = _org_with_teams()
    result = resolve_billing_teams(
        [], [_storage(t0.id, str(org.id), gib="100"), _storage(t0.id, str(org.id), gib="250")]
    )

    assert len(result.storage_rows) == 1
    assert result.storage_rows[0].gib_seconds == Decimal("250")  # kept the max
    assert result.conflicting_row_count == 1
    assert result.conflicting_org_ids == {str(org.id)}


# --- surrogate election: one query, strictly tenant-local -----------------------


def test_surrogate_election_never_crosses_orgs() -> None:
    # Org B owns the GLOBALLY lowest billable team id. A naive "lowest id across
    # the batch" election would hand org A's usage to org B's team — a
    # cross-tenant billing leak. Election must be lowest-per-org, always.
    org_a = Organization.objects.create(name="org a")
    Team.objects.create(id=40010, organization=org_a, name="a-low")
    Team.objects.create(id=40011, organization=org_a, name="a-high")
    org_b = Organization.objects.create(name="org b")
    Team.objects.create(id=40001, organization=org_b, name="b-global-lowest")

    result = resolve_billing_teams(
        [_compute(DEAD, str(org_a.id)), _compute(DEAD_2, str(org_b.id))],
        [],
    )

    by_org = {r.org_id: r.team_id for r in result.compute_rows}
    assert by_org == {str(org_a.id): 40010, str(org_b.id): 40001}  # each org its OWN lowest
    assert result.orphaned_org_ids == set()


def test_orphan_org_stays_orphan_in_a_batch_with_billable_orgs() -> None:
    # The single shared election query must not bleed between orgs: an org with
    # no billable team is orphaned even when the same pull carries orgs that
    # elect successfully.
    org_ok, (t0, _) = _org_with_teams()
    org_orphan = Organization.objects.create(name="no teams")

    result = resolve_billing_teams(
        [_compute(DEAD, str(org_ok.id)), _compute(DEAD_2, str(org_orphan.id))],
        [],
    )

    by_org = {r.org_id: r.team_id for r in result.compute_rows}
    assert by_org[str(org_ok.id)] == t0.id  # elected normally
    assert by_org[str(org_orphan.id)] == DEAD_2  # retained for report-time attribution
    assert result.orphaned_org_ids == {str(org_orphan.id)}


def test_election_query_count_is_constant_in_org_count(django_assert_num_queries) -> None:
    # The election is ONE query however many orgs carry dead stamps (it was a
    # per-org N+1; a pull can carry thousands of affected orgs). Two queries
    # total: team liveness + election.
    orgs = []
    for i in range(5):
        org = Organization.objects.create(name=f"org {i}")
        Team.objects.create(id=41000 + i, organization=org, name=f"t{i}")
        orgs.append(org)

    rows = [_compute(DEAD, str(org.id)) for org in orgs]
    with django_assert_num_queries(2):
        result = resolve_billing_teams(rows, [])

    assert {r.team_id for r in result.compute_rows} == {41000 + i for i in range(5)}


# --- conflict tie-break uses billable value, not raw lexicographic ------------
# A value conflict keeps the row that bills MORE. "More" is the billable
# compute-seconds (cpu_seconds*8 + memory_seconds), NOT a lexicographic compare of
# (cpu_seconds, memory_seconds) — the latter would keep a row with a larger
# cpu_seconds even when the other row's memory makes it the pricier one.


def test_conflict_keeps_the_pricier_row_by_billable_value() -> None:
    org, (t0, _) = _org_with_teams()
    # Same billing key, different measures. cheaper bills 100*8 + 0 = 800; pricier
    # bills 99*8 + 1600 = 2392. A lexicographic (cpu_seconds, memory_seconds)
    # compare would wrongly keep cheaper (100 > 99).
    cheaper = _compute(t0.id, str(org.id), cpu_seconds=100, memory_seconds=0)
    pricier = _compute(t0.id, str(org.id), cpu_seconds=99, memory_seconds=1600)

    result = resolve_billing_teams([cheaper, pricier], [])

    assert len(result.compute_rows) == 1
    kept = result.compute_rows[0]
    assert (kept.cpu_seconds, kept.memory_seconds) == (99, 1600)  # the pricier one, not the larger cpu_seconds
    assert result.conflicting_row_count == 1


def test_conflict_keeps_the_pricier_row_even_when_it_arrives_first() -> None:
    # keep-pricier must not depend on order: the pricier row arriving first must not
    # be overwritten by the cheaper one that follows.
    org, (t0, _) = _org_with_teams()
    pricier = _compute(t0.id, str(org.id), cpu_seconds=99, memory_seconds=1600)  # bills 2392
    cheaper = _compute(t0.id, str(org.id), cpu_seconds=100, memory_seconds=0)  # bills 800

    result = resolve_billing_teams([pricier, cheaper], [])

    assert len(result.compute_rows) == 1
    kept = result.compute_rows[0]
    assert (kept.cpu_seconds, kept.memory_seconds) == (99, 1600)
    assert result.conflicting_row_count == 1


# --- a live team belonging to a DIFFERENT org is a foreign-team drop -----------
# duckgres stamps the org's own team; a row whose live team belongs to another org
# is a duckgres/provisioning bug. We drop it (never charge the wrong org — the org
# is the billing authority) and surface it; the ack still proceeds.


def test_row_with_live_team_from_a_different_org_is_dropped_and_flagged() -> None:
    org_a, (a0, _) = _org_with_teams()
    org_b, (b0,) = _org_with_teams(n=1)
    good = _compute(a0.id, str(org_a.id))  # org A's own live team — kept
    foreign = _compute(b0.id, str(org_a.id), date=dt.date(2026, 7, 7))  # org B's live team on org A — dropped

    result = resolve_billing_teams([good, foreign], [])

    assert result.compute_rows == [good]  # only the foreign row was dropped
    assert result.foreign_team_row_count == 1
    assert result.foreign_team_sample == (b0.id,)
    assert result.orphaned_org_ids == set()  # a foreign-team drop, not an orphan org


def test_foreign_team_storage_row_is_dropped_and_flagged() -> None:
    org_a, _ = _org_with_teams()
    org_b, (b0,) = _org_with_teams(n=1)

    result = resolve_billing_teams([], [_storage(b0.id, str(org_a.id))])

    assert result.storage_rows == []
    assert result.foreign_team_row_count == 1
    assert result.foreign_team_sample == (b0.id,)


def test_foreign_row_dropped_but_dead_team_in_same_org_still_reattributed() -> None:
    # A foreign row and a genuinely-dead-team row in the same org: the foreign row is
    # dropped, the dead-team row is still remapped to the org's live surrogate.
    org_a, (a0, a1) = _org_with_teams()
    org_b, (b0,) = _org_with_teams(n=1)
    foreign = _compute(b0.id, str(org_a.id))  # org B's team on A — dropped
    dead = _compute(DEAD, str(org_a.id), date=dt.date(2026, 7, 7))  # dead in A — remapped to a0

    result = resolve_billing_teams([foreign, dead], [])

    assert {r.team_id for r in result.compute_rows} == {min(a0.id, a1.id)}  # foreign gone, dead remapped
    assert result.foreign_team_row_count == 1


def test_malformed_org_ids_are_dropped_counted_and_never_crash() -> None:
    # duckgres contract break: org keys must be PostHog org UUIDs (the dev
    # seed's org named 'local' is a live counter-example). Such rows can't
    # survive any DB touch, so they're quarantined before one — valid rows
    # unaffected, ack unaffected (asserted at the activity level).
    org, (t0, _) = _org_with_teams()
    rows = [
        _compute(t0.id, str(org.id)),  # valid, live stamp
        _compute(DEAD, "local"),  # malformed org, dead stamp
        _compute(t0.id, "not-a-uuid"),  # malformed org, live stamp
    ]
    storage = [_storage(t0.id, str(org.id)), _storage(DEAD, "local")]

    result = resolve_billing_teams(rows, storage)

    assert [r.org_id for r in result.compute_rows] == [str(org.id)]
    assert [r.org_id for r in result.storage_rows] == [str(org.id)]
    assert result.malformed_org_row_count == 3
    assert result.malformed_org_id_sample == ("local", "not-a-uuid")
    assert result.orphaned_org_ids == set()
