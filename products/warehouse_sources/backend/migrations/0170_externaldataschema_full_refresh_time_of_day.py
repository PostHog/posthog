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
        migrations.AlterField(
            model_name="externaldataschema",
            name="next_full_refresh_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the next scheduled full refresh is due. The first scheduled sync that starts at most an hour before this time re-imports the table. Saving a new interval or time, or any full resync, moves it one interval ahead, onto full_refresh_time_of_day when that is set.",
                null=True,
            ),
        ),
    ]
