from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0017_remove_slacksettings_ai_preferences"),
    ]

    # Phase 2 of the safe column drop, so that the state removal in 0017 can be
    # deployed before the column goes away. The reverse re-adds the column empty,
    # which lets the migration unapply but does not recover the dropped values.
    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "slack_app_slacksettings" DROP COLUMN IF EXISTS "ai_preferences";',
            reverse_sql='ALTER TABLE "slack_app_slacksettings" ADD COLUMN IF NOT EXISTS "ai_preferences" jsonb NULL;',
        ),
    ]
