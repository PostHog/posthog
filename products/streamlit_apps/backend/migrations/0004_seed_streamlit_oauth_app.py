"""Pre-create the Streamlit OAuth application as a data migration.

The Streamlit Apps feature mints OAuth tokens against a fixed first-party
application. Creating it lazily on first use (the previous get_or_create
pattern) was racy across workers and made it hard to reason about which row
the app code actually points at. Seeding it once via a data migration removes
the race and makes the row deletable only via the reverse migration.
"""

import secrets

from django.db import migrations

STREAMLIT_OAUTH_APP_NAME = "PostHog Streamlit Apps"


def seed_oauth_app(apps, schema_editor):
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")

    if OAuthApplication.objects.filter(name=STREAMLIT_OAUTH_APP_NAME).exists():
        return

    OAuthApplication.objects.create(
        name=STREAMLIT_OAUTH_APP_NAME,
        # Use AUTHORIZATION_CODE because the OAuthApplication CheckConstraint
        # forces this grant type. We never run the actual authorize redirect —
        # tokens are minted programmatically because is_first_party=True.
        client_type="confidential",
        authorization_grant_type="authorization-code",
        # Empty redirect_uris is enforced by the validator on save() in some
        # paths, so we set a non-network sentinel that satisfies the URL field
        # but still couldn't successfully complete a real authorize redirect.
        redirect_uris="https://localhost",
        client_id=secrets.token_urlsafe(32),
        client_secret=secrets.token_urlsafe(48),
        algorithm="RS256",
        is_first_party=True,
    )


def delete_oauth_app(apps, schema_editor):
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")
    OAuthApplication.objects.filter(name=STREAMLIT_OAUTH_APP_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("streamlit_apps", "0003_alter_sandbox_version_set_null"),
        ("posthog", "1004_resource_transfer"),
    ]

    operations = [
        migrations.RunPython(seed_oauth_app, reverse_code=delete_oauth_app),
    ]
