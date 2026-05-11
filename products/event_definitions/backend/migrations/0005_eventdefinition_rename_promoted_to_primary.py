from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("event_definitions", "0004_eventdefinition_team_name_idx"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name="eventdefinition",
                    old_name="promoted_property",
                    new_name="primary_property",
                ),
                migrations.AlterField(
                    model_name="eventdefinition",
                    name="primary_property",
                    field=models.CharField(
                        blank=True,
                        db_column="promoted_property",
                        max_length=400,
                        null=True,
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
