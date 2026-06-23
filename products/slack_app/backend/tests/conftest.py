"""Shared fixtures for slack_app backend tests.

The resolver's ``load_integrations`` now eagerly runs Slack ``auth.test`` on
cache miss (see ``services/slack_auth.check_integrations_auth_and_filter``).
Without intervention, every test that constructs an ``Integration`` row but
doesn't patch the Slack SDK ends up making the resolver try a real Slack call
with a fake token, which fails, drops the candidate, and breaks downstream
routing assertions in ways that have nothing to do with what the test is
actually checking.

This conftest neutralizes that for the whole package: by default, the
auth-state filter is a pass-through. Tests that actually want to exercise
the filter (``test_slack_auth.py``, ``TestLoadIntegrationsAuthStateFilter``)
opt back in by overriding the fixture or asserting against the real flow
behind a local patch.
"""

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _bypass_slack_auth_filter():
    """Pass-through the resolver's auth-state pre-filter for unit tests.

    The filter's job is to drop integrations whose bot token has gone bad.
    For tests that pre-construct an ``Integration`` with a stub
    ``access_token`` and never exercise the OAuth round-trip, the eager
    ``auth.test`` call would always fail and the resolver would always return
    an empty candidate list. That's the wrong default — most tests want to
    exercise *routing* against the integrations they created, not the
    auth-state mechanism itself.

    Tests that DO want to exercise the filter (``test_slack_auth.py``,
    ``TestLoadIntegrationsAuthStateFilter`` in ``test_integration_resolver.py``)
    stop this fixture from taking effect by patching at the module the
    resolver imports from — see those files for the pattern.
    """
    # ``load_integrations`` inline-imports ``check_integrations_auth_and_filter``
    # from ``slack_auth``, so we patch at the source module rather than at the
    # resolver's import site (the import re-runs on every call and would miss
    # an import-site patch).
    with patch(
        "products.slack_app.backend.services.slack_auth.check_integrations_auth_and_filter",
        side_effect=lambda candidates, **_: candidates,
    ):
        yield
