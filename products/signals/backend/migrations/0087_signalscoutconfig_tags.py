import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0086_signalscoutconfig_structured_output_schema"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalscoutconfig",
            name="tags",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=50),
                blank=True,
                default=list,
                null=True,
                size=None,
            ),
        ),
    ]
