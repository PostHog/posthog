import django.db.models.deletion
from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently


def _project_field() -> models.ForeignKey:
    return models.ForeignKey(
        db_index=False,
        null=True,
        on_delete=django.db.models.deletion.CASCADE,
        related_name="+",
        to="posthog.project",
    )


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("event_definitions", "0013_drop_propertydefinition_team_id_fk_idx"),
    ]

    # A database built from the squashed migrations gets Django's automatic ForeignKey index on
    # project_id next to the named Meta index on `project`, which has the same definition. Databases
    # that ran the original history (posthog 0528) never had the automatic index, so each drop
    # is a no-op there and the named index stays on every database.
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(model_name=model_name, name="project", field=_project_field())
                for model_name in ("propertydefinition", "eventdefinition", "eventproperty")
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="posthog_propertydefinition_project_id_d3eb982d",
                    table_name="posthog_propertydefinition",
                    columns="(project_id)",
                ),
                DropIndexConcurrently(
                    index_name="posthog_eventdefinition_project_id_f93fcbb0",
                    table_name="posthog_eventdefinition",
                    columns="(project_id)",
                ),
                DropIndexConcurrently(
                    index_name="posthog_eventproperty_project_id_dd2337d2",
                    table_name="posthog_eventproperty",
                    columns="(project_id)",
                ),
            ],
        ),
    ]
