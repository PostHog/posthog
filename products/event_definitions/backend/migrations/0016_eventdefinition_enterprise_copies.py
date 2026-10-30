import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("event_definitions", "0015_drop_index_property_def_query")]

    # Database only: the model does not declare these columns yet, see enterprise_copies.py. The
    # field names exist only inside this operation. Nullable with no default, so each ADD COLUMN only
    # changes the catalog.
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.AddField(
                    model_name="eventdefinition",
                    name="copy_description",
                    field=models.TextField(null=True, db_column="description"),
                ),
                migrations.AddField(
                    model_name="eventdefinition",
                    name="copy_owner_id",
                    field=models.IntegerField(null=True, db_column="owner_id"),
                ),
                migrations.AddField(
                    model_name="eventdefinition",
                    name="copy_updated_at",
                    field=models.DateTimeField(null=True, db_column="updated_at"),
                ),
                migrations.AddField(
                    model_name="eventdefinition",
                    name="copy_updated_by_id",
                    field=models.IntegerField(null=True, db_column="updated_by_id"),
                ),
                migrations.AddField(
                    model_name="eventdefinition",
                    name="copy_verified",
                    field=models.BooleanField(null=True, db_column="verified"),
                ),
                migrations.AddField(
                    model_name="eventdefinition",
                    name="copy_verified_at",
                    field=models.DateTimeField(null=True, db_column="verified_at"),
                ),
                migrations.AddField(
                    model_name="eventdefinition",
                    name="copy_verified_by_id",
                    field=models.IntegerField(null=True, db_column="verified_by_id"),
                ),
                migrations.AddField(
                    model_name="eventdefinition",
                    name="copy_hidden",
                    field=models.BooleanField(null=True, db_column="hidden"),
                ),
                migrations.AddField(
                    model_name="eventdefinition",
                    name="copy_default_columns",
                    field=django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), null=True, db_column="default_columns"
                    ),
                ),
            ],
            state_operations=[],
        ),
    ]
