import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("event_definitions", "0016_eventdefinition_enterprise_copies"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    # Nullable columns, so each ADD COLUMN only changes the catalog.
    operations = [
        migrations.AddField(
            model_name="propertydefinition",
            name="base_description",
            field=models.TextField(blank=True, db_column="description", null=True),
        ),
        migrations.AddField(
            model_name="propertydefinition",
            name="base_hidden",
            field=models.BooleanField(blank=True, db_column="hidden", default=False, null=True),
        ),
        migrations.AddField(
            model_name="propertydefinition",
            name="base_updated_at",
            field=models.DateTimeField(blank=True, db_column="updated_at", null=True),
        ),
        migrations.AddField(
            model_name="propertydefinition",
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
            model_name="propertydefinition",
            name="base_verified",
            field=models.BooleanField(blank=True, db_column="verified", default=False, null=True),
        ),
        migrations.AddField(
            model_name="propertydefinition",
            name="base_verified_at",
            field=models.DateTimeField(blank=True, db_column="verified_at", null=True),
        ),
        migrations.AddField(
            model_name="propertydefinition",
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
