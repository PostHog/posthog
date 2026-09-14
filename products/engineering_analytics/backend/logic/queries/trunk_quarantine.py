"""The standing Trunk quarantine debt, attributed to owning teams.

The quarantined set comes from the synced TrunkIo ``QuarantinedTests`` warehouse table; ownership
from the repository's own files (``logic.ownership``), because a quarantine outlives the CI signal
that would otherwise name a team. A test the repo cannot place, or whose path no team claims, lands
under ``'unowned'``.
"""

from datetime import UTC, datetime, timedelta

from products.engineering_analytics.backend.facade.contracts import (
    TrunkQuarantineDebt,
    TrunkQuarantinedTest,
    TrunkQuarantineTeamDebt,
)
from products.engineering_analytics.backend.logic.ownership import QuarantinedTestFile, resolve_test_ownership
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

_QUARANTINED_SELECT = """
    SELECT runner, nodeid, source_path, crate, status, quarantine_setting, test_case_id, quarantined_at
    FROM __TRUNK_SOURCE__
"""


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
    ttl_days: int,
    now: datetime,
) -> TrunkQuarantineDebt:
    """Every currently quarantined test with its owning team and age, plus the per-team rollup;
    the unavailable shape when no TrunkIo QuarantinedTests table is synced."""
    source = curated.trunk_quarantined_tests_source()
    if source is None:
        return TrunkQuarantineDebt(
            available=False,
            owners_resolved=True,
            ttl_days=ttl_days,
            repository=curated.repository,
            trunk_url=None,
            teams=[],
            tests=[],
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
            available=True,
            owners_resolved=True,
            ttl_days=ttl_days,
            repository=curated.repository,
            trunk_url=trunk_url,
            teams=[],
            tests=[],
        )

    parsed = [
        (runner, nodeid, QuarantinedTestFile(source_path=source_path, crate=crate), status, setting, case_id, at)
        for runner, nodeid, source_path, crate, status, setting, case_id, at in rows
    ]
    owned_by_test = resolve_test_ownership(curated.repository, [row[2] for row in parsed])
    tests: list[TrunkQuarantinedTest] = []
    for (runner, nodeid, _file, status, quarantine_setting, test_case_id, quarantined_at), owned in zip(
        parsed, owned_by_test.tests, strict=True
    ):
        if quarantined_at.tzinfo is None:
            quarantined_at = quarantined_at.replace(tzinfo=UTC)
        age_days = max((now - quarantined_at) // timedelta(days=1), 0)
        tests.append(
            TrunkQuarantinedTest(
                runner=runner,
                nodeid=nodeid,
                file=owned.path,
                owner_team=owned.owner_team,
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
            test_count=len(owned_tests),
            overdue_count=sum(1 for test in owned_tests if test.overdue),
            # tests is sorted oldest first above, so each owner's first entry carries the max age
            oldest_age_days=owned_tests[0].age_days,
        )
        for owner_team, owned_tests in rollup.items()
    ]
    teams.sort(key=lambda team: (-team.overdue_count, -team.test_count, -team.oldest_age_days, team.owner_team))
    return TrunkQuarantineDebt(
        available=True,
        owners_resolved=owned_by_test.resolved,
        ttl_days=ttl_days,
        repository=curated.repository,
        trunk_url=trunk_url,
        teams=teams,
        tests=tests,
    )
