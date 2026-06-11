from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0005_alter_externaldatasource_source_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="row_filters",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
