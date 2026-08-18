from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0090_alter_origin_product_signals_chat")]

    operations = [
        # No default here on purpose: a field default makes Django emit `ADD COLUMN ... DEFAULT`,
        # which stamps every existing row with one migration-time value and leaves the backfill in
        # 0092 nothing to fill. Existing rows land NULL, 0092 seeds them from their real history,
        # and 0093 adds the default for rows created afterwards.
        migrations.AddField(
            model_name="task",
            name="last_activity_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
