import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0103_callable_choices"),
    ]

    operations = [
        migrations.CreateModel(
            name="DesktopBetaTermsAcceptance",
            fields=[
                (
                    "organization",
                    models.OneToOneField(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="posthog.organization",
                    ),
                ),
                ("accepted_by_user_id", models.BigIntegerField()),
                ("accepted_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
