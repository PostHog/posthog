from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0017_remove_slacksettings_ai_preferences"),
    ]

    # Phase 2 of the safe column drop: 0017 removed the field from Django state
    # while the column stayed for the previous release and its rollback window.
    # This drops the column itself; the reverse re-adds it empty so the
    # migration unapplies, but the values (already migrated to the tasks config
    # by 0016, or unattributable) are gone for good.
    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "slack_app_slacksettings" DROP COLUMN IF EXISTS "ai_preferences";',
            reverse_sql='ALTER TABLE "slack_app_slacksettings" ADD COLUMN IF NOT EXISTS "ai_preferences" jsonb NULL;',
        ),
    ]
