from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0124_rename_planetscale_source_type_to_mysql")]

    operations = [
        migrations.AddField(
            model_name="externaldataschemaoomevent",
            name="self_phase",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="externaldataschemaoomevent",
            name="self_report_age_at_death_seconds",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="externaldataschemaoomevent",
            name="self_peak_buffer_bytes",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="externaldataschemaoomevent",
            name="co_tenant_correlated_max_peak_buffer_bytes",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="externaldataschemaoomevent",
            name="co_tenant_report_count",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
