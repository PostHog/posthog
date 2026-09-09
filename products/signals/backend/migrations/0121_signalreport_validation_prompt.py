from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0120_signaluserautonomyconfig_github_assign"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="validation_prompt",
            field=models.TextField(blank=True, null=True),
        ),
    ]
