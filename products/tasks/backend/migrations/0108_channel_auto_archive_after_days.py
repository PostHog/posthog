from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0107_remove_code_invites_from_state")]

    operations = [
        migrations.AddField(
            model_name="channel",
            name="auto_archive_after_days",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(1, "1 day"), (3, "3 days"), (7, "7 days"), (14, "14 days"), (30, "30 days")],
                help_text=(
                    "Archive inactive tasks in this channel after this many days. Null disables automatic archiving."
                ),
                null=True,
            ),
        ),
    ]
