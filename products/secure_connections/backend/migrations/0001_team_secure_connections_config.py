import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [("posthog", "1279_drop_duckgresserverteam_table")]

    operations = [
        migrations.CreateModel(
            name="TeamSecureConnectionsConfig",
            fields=[
                (
                    "team",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="posthog.team",
                    ),
                ),
                ("cdp_approved_connections", models.JSONField(default=dict)),
            ],
        )
    ]
