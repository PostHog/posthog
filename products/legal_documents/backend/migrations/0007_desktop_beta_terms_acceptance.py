import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("legal_documents", "0006_backfill_signed_pdf_stored"),
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
