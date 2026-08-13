from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0089_taskrun_queued_at")]

    operations = [
        # No default here on purpose: a field default makes Django emit `ADD COLUMN ... DEFAULT`,
        # which stamps every existing row with one migration-time value and leaves the backfill in
        # 0091 nothing to fill. Existing rows land NULL, 0091 seeds them from their real history,
        # and 0092 adds the default for rows created afterwards.
        migrations.AddField(
            model_name="task",
            name="last_activity_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
