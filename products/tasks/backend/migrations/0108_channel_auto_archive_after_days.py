from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0107_remove_code_invites_from_state")]

    operations = [
        migrations.AddField(
            model_name="channel",
            name="auto_archive_after_days",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text=(
                    "Archive inactive tasks in this channel after this many days. Null disables automatic archiving."
                ),
                null=True,
            ),
        ),
    ]
