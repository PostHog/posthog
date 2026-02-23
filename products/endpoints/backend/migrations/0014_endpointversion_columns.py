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
                null=True,
                help_text="SELECT column names and types. Null means not yet computed; empty list means no columns found.",
            ),
        ),
    ]
