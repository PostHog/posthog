from django.db import migrations

# Every personal row that exists before onboarding ships belongs to someone who already used the Slack
# app, so they must not get onboarding. Rows created later start with a NULL onboarding and stay eligible.
MARK_EXISTING_USERS_ONBOARDED_SQL = """
-- migration-analyzer: safe reason=one UPDATE of the small per-Slack-user settings table; it only fills the column 0024 adds
UPDATE slack_app_slacksettings
SET onboarding = jsonb_build_object(
    'completed_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
    'completed_reason', 'legacy',
    'version', 1
)
WHERE slack_user_id IS NOT NULL
  AND onboarding IS NULL;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0024_slacksettings_onboarding"),
    ]

    operations = [
        migrations.RunSQL(MARK_EXISTING_USERS_ONBOARDED_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
