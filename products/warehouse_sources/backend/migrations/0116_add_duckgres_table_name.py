from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0115_scaffold_four_requested_sources"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="duckgres_table_name",
            field=models.CharField(blank=True, max_length=63, null=True),
        ),
    ]
