"""Test-suite fixtures for the streamlit_apps backend.

`_streamlit_team_scope` auto-wraps every test that has a `self.team` (i.e. is
built on `BaseTest`/`APIBaseTest`) in `team_scope(self.team.id)`. `StreamlitApp`
uses `TeamScopedRootMixin`, so its default `.objects` manager is fail-closed and
raises `TeamScopeError` when called outside a team context. Test setUp / body
code that does `StreamlitApp.objects.create(...)` directly (without going
through a DRF request that sets context via `TeamAndOrgViewSetMixin.initial`)
would otherwise need an explicit `with team_scope(...)` wrapper everywhere.

The fixture is a no-op for tests without a `team` attribute (pure unit tests
like the auth-proxy and zip-validator suites). Same pattern as
products/signals/backend/test/conftest.py.
"""

from __future__ import annotations

import pytest

from posthog.models.scoping import team_scope


@pytest.fixture(autouse=True)
def _streamlit_team_scope(request: pytest.FixtureRequest):
    instance = getattr(request, "instance", None)
    if instance is None or getattr(instance, "team", None) is None:
        yield
        return
    with team_scope(instance.team.id):
        yield
