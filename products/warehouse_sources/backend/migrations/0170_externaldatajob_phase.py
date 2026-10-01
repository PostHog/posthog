from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0169_warehousecolumnstatistics_full_scan_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldatajob",
            name="phase",
            field=models.CharField(
                blank=True,
                choices=[("extracting", "Extracting"), ("loading", "Loading"), ("post_actions", "Post Actions")],
                max_length=16,
                null=True,
            ),
        ),
    ]
