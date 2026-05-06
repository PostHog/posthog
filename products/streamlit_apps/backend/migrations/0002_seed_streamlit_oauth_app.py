"""Pre-create the Streamlit OAuth application as a data migration.

The Streamlit Apps feature mints OAuth tokens against a fixed first-party
application. Creating it lazily on first use was racy across workers and made
it hard to reason about which row the app code actually points at. Seeding it
once via a data migration removes the race and makes the row deletable only
via the reverse migration.

The client_id is deterministic (not a random secret) so that re-running the
migration (forward → reverse → forward) is a true no-op in dev — the row that
gets re-created has the same client_id the rest of the system already expects.
The client_secret is always fresh because it IS meant to be a secret.

Grant type is "authorization-code" because OAuthApplication has a
CheckConstraint (see posthog/models/oauth.py :: enforce_supported_grant_types)
that rejects every other grant type. We never actually run the authorize
redirect — tokens are minted programmatically because is_first_party=True
skips the consent screen — so the grant type is effectively unused, but it
has to be set to something that passes the check.
"""

import secrets

from django.db import migrations

STREAMLIT_OAUTH_APP_NAME = "PostHog Streamlit Apps"
STREAMLIT_OAUTH_CLIENT_ID = "posthog-streamlit-apps-first-party"


def seed_oauth_app(apps, schema_editor):
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")

    if OAuthApplication.objects.filter(client_id=STREAMLIT_OAUTH_CLIENT_ID).exists():
        return

    OAuthApplication.objects.create(
        name=STREAMLIT_OAUTH_APP_NAME,
        client_id=STREAMLIT_OAUTH_CLIENT_ID,
        client_secret=secrets.token_urlsafe(48),
        client_type="confidential",
        authorization_grant_type="authorization-code",
        # Non-empty loopback URI satisfies OAuthApplication.clean() even
        # though we never actually redirect. Empty string also validates,
        # but a real-looking value is clearer to anyone reading the row.
        redirect_uris="https://localhost",
        algorithm="RS256",
        is_first_party=True,
    )


def delete_oauth_app(apps, schema_editor):
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")
    # Delete by client_id, not name — `name` is user-editable via the admin
    # and a renamed row would silently survive a reverse migration.
    OAuthApplication.objects.filter(client_id=STREAMLIT_OAUTH_CLIENT_ID).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("streamlit_apps", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_oauth_app, reverse_code=delete_oauth_app),
    ]
