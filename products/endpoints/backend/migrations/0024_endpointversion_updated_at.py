from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0023_backfill_team_id_on_endpointversion_fix"),
    ]

    operations = [
        migrations.AddField(
            model_name="endpointversion",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True, blank=True),
        ),
    ]
