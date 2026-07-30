import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("feature_flags", "0011_clean_flag_filters_recoverable_violations"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeamFeatureFlagGuidelinesConfig",
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
                ("enabled", models.BooleanField(default=False)),
                ("url", models.CharField(blank=True, default="", max_length=800)),
            ],
        ),
    ]
