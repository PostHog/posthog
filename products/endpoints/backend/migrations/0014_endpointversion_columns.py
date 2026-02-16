from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0013_add_endpointversion_is_active"),
    ]

    operations = [
        migrations.AddField(
            model_name="endpointversion",
            name="columns",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="SELECT column names parsed from the query at creation time",
            ),
        ),
    ]
