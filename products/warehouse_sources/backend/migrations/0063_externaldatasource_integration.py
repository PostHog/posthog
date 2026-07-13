import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0062_alter_externaldatasource_source_type_and_more"),
        ("posthog", "1251_alter_integration_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldatasource",
            name="integration",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="external_data_sources",
                to="posthog.integration",
            ),
        ),
    ]
