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

import pytest

from posthog.models.scoping import team_scope


@pytest.fixture(autouse=True)
def _scout_team_scope(request: pytest.FixtureRequest):
    instance = getattr(request, "instance", None)
    if instance is None or not hasattr(instance, "team") or instance.team is None:
        yield
        return
    with team_scope(instance.team.id):
        yield
