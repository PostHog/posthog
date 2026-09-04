from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    """Validate the team FK separately so creating the context table stays non-blocking."""

    dependencies = [
        ("exports", "0012_subscription_context"),
    ]

    operations = [
        ValidateForeignKey(model_name="subscriptioncontext", name="subscriptioncontext_team_id_fk"),
    ]
