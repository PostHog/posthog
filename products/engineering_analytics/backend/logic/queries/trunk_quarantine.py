"""The standing Trunk quarantine debt, attributed to owning teams.

Two substrates, joined in Python because they live on different clusters: the quarantined set from
the synced TrunkIo ``QuarantinedTests`` warehouse table, and ownership from the per-test CI spans
on the LOGS cluster (the emitter stamps ``test.owner_team``; SPEC locks ownership to that stamp,
never a server-side map). A quarantined test with no in-retention span lands under ``'unowned'``.

Trunk keys a test by (file, classname, name); the curated builder reconstructs the runner-native
nodeid from that key, and the span side reports the same id as the span name — but each side can
carry a longer path prefix (product suites run from their product dir), so the join matches on
path suffixes rather than exact equality.
"""

from datetime import UTC, datetime, timedelta

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    TrunkQuarantineDebt,
    TrunkQuarantinedTest,
    TrunkQuarantineTeamDebt,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._test_spans import (
    UNOWNED_TEAM,
    run_evidence,
    scan_placeholders,
)

# One owner per test, resolved by its latest ownership stamp (same rule as the team rollups). The
# selector rides along because it is the runner-native id Trunk's key reconstructs to; the span
# nodeid folds the pytest file/class boundary and never matches a Trunk key directly.
_OWNER_ROSTER_SELECT = f"""
    SELECT runner, nodeid, anyIf(selector, selector != '') AS selector, argMax(owner_team, run_signal_at) AS owner_team
    FROM ({run_evidence(bounded=False)})
    GROUP BY runner, nodeid
"""

_QUARANTINED_SELECT = """
    SELECT runner, nodeid, file, status, quarantine_setting, test_case_id, quarantined_at
    FROM __TRUNK_SOURCE__
"""


def _nodeid_variants(nodeid: str) -> list[str]:
    """Every path-suffix variant of a nodeid, so either join side can hold the longer prefix.
    Stops above the bare filename, where two packages' same-named files would collide."""
    path, sep, tail = nodeid.partition("::")
    suffix = f"{sep}{tail}" if sep else ""
    segments = path.split("/")
    variants = [f"{'/'.join(segments[start:])}{suffix}" for start in range(max(len(segments) - 1, 1))]
    return variants or [nodeid]


def _trunk_url(org_url_slug: str | None, repository: str) -> str | None:
    if not org_url_slug:
        return None
    return f"https://app.trunk.io/{org_url_slug}/flaky-tests?repo={repository}"


def _trunk_test_url(org_url_slug: str | None, repository: str, test_case_id: str) -> str | None:
    """The Trunk app's per-test page. The ``?repo`` form is what Trunk itself redirects to the
    canonical repo-uuid URL (verified against the live app); the uuid is not in the synced data."""
    if not org_url_slug or not test_case_id:
        return None
    return f"https://app.trunk.io/{org_url_slug}/flaky-tests/test/{test_case_id}?repo={repository}"


def query_trunk_quarantine_debt(
    *,
    curated: CuratedGitHubSource,
    owner_window_from: datetime,
    ttl_days: int,
    now: datetime,
) -> TrunkQuarantineDebt:
    """Every currently quarantined test with its owning team and age, plus the per-team rollup;
    the unavailable shape when no TrunkIo QuarantinedTests table is synced."""
    source = curated.trunk_quarantined_tests_source()
    if source is None:
        return TrunkQuarantineDebt(
            available=False, ttl_days=ttl_days, repository=curated.repository, trunk_url=None, teams=[], tests=[]
        )
    org_url_slug = curated.trunk_org_url_slug()
    trunk_url = _trunk_url(org_url_slug, curated.repository)

    quarantined = curated.run(
        _QUARANTINED_SELECT.replace("__TRUNK_SOURCE__", source),
        query_type="engineering_analytics.trunk_quarantine_debt",
        placeholders={},
    )
    rows = quarantined.results or []
    if not rows:
        return TrunkQuarantineDebt(
            available=True, ttl_days=ttl_days, repository=curated.repository, trunk_url=trunk_url, teams=[], tests=[]
        )

    owners = curated.run(
        _OWNER_ROSTER_SELECT,
        query_type="engineering_analytics.trunk_quarantine_owners",
        placeholders=scan_placeholders(repository=curated.repository, date_from=owner_window_from),
        workload=Workload.LOGS,
    )
    owner_by_variant: dict[tuple[str, str], str] = {}
    for runner, nodeid, selector, owner_team in owners.results or []:
        for key in (nodeid, selector):
            if not key:
                continue
            for variant in _nodeid_variants(key):
                owner_by_variant[(runner, variant)] = owner_team

    tests: list[TrunkQuarantinedTest] = []
    for runner, nodeid, file, status, quarantine_setting, test_case_id, quarantined_at in rows:
        owner = next(
            (
                owner_by_variant[(runner, variant)]
                for variant in _nodeid_variants(nodeid)
                if (runner, variant) in owner_by_variant
            ),
            UNOWNED_TEAM,
        )
        if quarantined_at.tzinfo is None:
            quarantined_at = quarantined_at.replace(tzinfo=UTC)
        age_days = max((now - quarantined_at) // timedelta(days=1), 0)
        tests.append(
            TrunkQuarantinedTest(
                runner=runner,
                nodeid=nodeid,
                file=file,
                owner_team=owner,
                status=status,
                quarantine_setting=quarantine_setting,
                quarantined_at=quarantined_at,
                age_days=age_days,
                overdue=age_days > ttl_days,
                trunk_url=_trunk_test_url(org_url_slug, curated.repository, test_case_id),
            )
        )
    tests.sort(key=lambda test: (-test.age_days, test.nodeid))

    rollup: dict[str, list[TrunkQuarantinedTest]] = {}
    for test in tests:
        rollup.setdefault(test.owner_team, []).append(test)
    teams = [
        TrunkQuarantineTeamDebt(
            owner_team=owner_team,
            test_count=len(owned),
            overdue_count=sum(1 for test in owned if test.overdue),
            # tests is sorted oldest first above, so each owner's first entry carries the max age
            oldest_age_days=owned[0].age_days,
        )
        for owner_team, owned in rollup.items()
    ]
    teams.sort(key=lambda team: (-team.overdue_count, -team.test_count, -team.oldest_age_days, team.owner_team))
    return TrunkQuarantineDebt(
        available=True, ttl_days=ttl_days, repository=curated.repository, trunk_url=trunk_url, teams=teams, tests=tests
    )
