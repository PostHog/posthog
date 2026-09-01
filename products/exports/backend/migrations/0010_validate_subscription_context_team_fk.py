from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("exports", "0009_subscription_context"),
    ]

    operations = [
        ValidateForeignKey(model_name="subscriptioncontext", name="subscriptioncontext_team_id_fk"),
    ]
