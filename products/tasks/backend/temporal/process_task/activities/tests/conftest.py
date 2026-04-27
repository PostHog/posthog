import os

import pytest

from posthog.models import OAuthApplication

from products.tasks.backend.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV


def _runs_on_internal_pr() -> bool:
    value = os.getenv("RUNS_ON_INTERNAL_PR")
    if value is None:
        return True
    return value.lower() in {"1", "true"}


@pytest.fixture(autouse=True)
def posthog_code_oauth_app(request):
    """Override parent autouse fixture — only create the OAuth app for DB-backed tests."""
    has_db = "django_db" in {m.name for m in request.node.iter_markers()}
    if not has_db:
        yield None
        return

    if not _runs_on_internal_pr():
        pytest.skip("Skipping test that requires internal secrets on external PRs")
    app, _ = OAuthApplication.objects.get_or_create(
        client_id=ARRAY_APP_CLIENT_ID_DEV,
        defaults={
            "name": "Array Test App",
            "client_type": OAuthApplication.CLIENT_PUBLIC,
            "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": "https://app.posthog.com/callback",
            "algorithm": "RS256",
        },
    )
    yield app
