"""Test-suite fixtures for the signals backend.

`_scout_team_scope` auto-wraps every test that has a `self.team` (i.e. is built
on `BaseTest`/`APIBaseTest`) in `team_scope(self.team.id)`. The scout models
(`SignalScoutConfig`, `SignalScoutRun`, `SignalScratchpad`) use
`TeamScopedRootMixin`, so their default `.objects` manager is fail-closed and
raises `TeamScopeError` when called outside a team context. Test setUp / body
code that does `Model.objects.create(...)` directly (without going through a
DRF request that sets context via `TeamAndOrgViewSetMixin.initial`) would
otherwise need an explicit `with team_scope(...)` wrapper everywhere.

The fixture is a no-op for tests that don't have a `team` attribute (pure unit
tests, async harness tests with their own setup) — those keep working unchanged.
The fixture is also harmless for non-scout tests in this directory: the older
`Signal*` models don't read the ContextVar.
"""

from __future__ import annotations

import random

import pytest

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope


@pytest.fixture(autouse=True)
def _scout_team_scope(request: pytest.FixtureRequest):
    instance = getattr(request, "instance", None)
    if instance is None or not hasattr(instance, "team") or instance.team is None:
        yield
        return
    with team_scope(instance.team.id):
        yield


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"SignalsTelemetryOrg-{random.randint(1, 99999)}",
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsTelemetryTeam-{random.randint(1, 99999)}",
    )
    yield team
    await sync_to_async(team.delete)()
