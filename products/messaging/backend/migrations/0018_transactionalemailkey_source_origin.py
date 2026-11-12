from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0017_transactionalemailkey_source_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="transactionalemailkey",
            name="source_origin",
            field=models.CharField(
                choices=[("manual", "Manual"), ("detected", "Detected from GitHub")],
                max_length=16,
                null=True,
            ),
        ),
    ]
