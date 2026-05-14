import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("founder_mode", "0002_marketing_columns"),
        ("posthog", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="founderproject",
            name="current_step",
            field=models.CharField(
                choices=[
                    ("ideation", "Ideation"),
                    ("validation", "Validation"),
                    ("gtm", "Gtm"),
                    ("mvp", "Mvp"),
                    ("marketing", "Marketing"),
                ],
                default="ideation",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="founderproject",
            name="team",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="founder_project",
                to="posthog.team",
            ),
        ),
    ]
