from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0169_warehousecolumnstatistics_full_scan_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="full_refresh_time_of_day",
            field=models.TimeField(
                blank=True,
                help_text="UTC time of day that scheduled full refreshes are due. Null means one interval after the last full resync or save.",
                null=True,
            ),
        ),
    ]
