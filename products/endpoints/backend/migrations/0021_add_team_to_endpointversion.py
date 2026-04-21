import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0020_backfill_endpoint_edges"),
    ]

    operations = [
        migrations.AddField(
            model_name="endpointversion",
            name="team",
            field=models.ForeignKey(
                help_text="Team this version belongs to (denormalized from endpoint for HogQL system table access)",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="posthog.team",
            ),
        )
    ]
