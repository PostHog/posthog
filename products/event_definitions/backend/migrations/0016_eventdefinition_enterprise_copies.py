import django.db.models.deletion
import django.contrib.postgres.fields
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("event_definitions", "0015_drop_index_property_def_query"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    # Nullable columns, or a constant default, so each ADD COLUMN only changes the catalog.
    operations = [
        migrations.AddField(
            model_name="eventdefinition",
            name="base_default_columns",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.TextField(), blank=True, db_column="default_columns", null=True, size=None
            ),
        ),
        migrations.AddField(
            model_name="eventdefinition",
            name="base_description",
            field=models.TextField(blank=True, db_column="description", null=True),
        ),
        migrations.AddField(
            model_name="eventdefinition",
            name="base_hidden",
            field=models.BooleanField(blank=True, db_column="hidden", db_default=False, default=False, null=True),
        ),
        migrations.AddField(
            model_name="eventdefinition",
            name="base_owner",
            field=models.ForeignKey(
                blank=True,
                db_column="owner_id",
                db_constraint=False,
                db_index=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="eventdefinition",
            name="base_updated_at",
            field=models.DateTimeField(blank=True, db_column="updated_at", null=True),
        ),
        migrations.AddField(
            model_name="eventdefinition",
            name="base_updated_by",
            field=models.ForeignKey(
                blank=True,
                db_column="updated_by_id",
                db_constraint=False,
                db_index=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="eventdefinition",
            name="base_verified",
            field=models.BooleanField(blank=True, db_column="verified", db_default=False, default=False),
        ),
        migrations.AddField(
            model_name="eventdefinition",
            name="base_verified_at",
            field=models.DateTimeField(blank=True, db_column="verified_at", null=True),
        ),
        migrations.AddField(
            model_name="eventdefinition",
            name="base_verified_by",
            field=models.ForeignKey(
                blank=True,
                db_column="verified_by_id",
                db_constraint=False,
                db_index=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
