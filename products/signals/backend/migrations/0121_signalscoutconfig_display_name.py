from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0120_signaluserautonomyconfig_github_assign"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalscoutconfig",
            name="display_name",
            field=models.CharField(
                blank=True,
                db_default="",
                default="",
                help_text="Name shown in the UI. Does not change the skill name. Leave blank to use the default name.",
                max_length=200,
            ),
        ),
    ]
