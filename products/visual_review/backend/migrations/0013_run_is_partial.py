from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("visual_review", "0012_quarantined_identifier_source_run"),
    ]

    operations = [
        migrations.AddField(
            model_name="run",
            name="is_partial",
            field=models.BooleanField(default=False),
        ),
    ]
