from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("notifications", "0022_add_notification_idempotency_key"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="notificationevent",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("idempotency_key__isnull", False), ("team__isnull", False)),
                        fields=("team", "idempotency_key"),
                        name="notification_event_team_idempotency_key_uniq",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="notificationevent",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("idempotency_key__isnull", False), ("team__isnull", True)),
                        fields=("organization", "idempotency_key"),
                        name="notification_event_organization_idempotency_key_uniq",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="notification_event_team_idempotency_key_uniq",
                    table_name="notifications_notificationevent",
                    columns="(team_id, idempotency_key) WHERE idempotency_key IS NOT NULL AND team_id IS NOT NULL",
                    unique=True,
                ),
                CreateIndexConcurrently(
                    index_name="notification_event_organization_idempotency_key_uniq",
                    table_name="notifications_notificationevent",
                    columns=(
                        "(organization_id, idempotency_key) WHERE idempotency_key IS NOT NULL AND team_id IS NULL"
                    ),
                    unique=True,
                ),
            ],
        ),
    ]
