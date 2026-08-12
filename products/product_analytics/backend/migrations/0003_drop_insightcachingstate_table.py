# Drops the posthog_insightcachingstate table. The model was removed from Django state in
# 0002_delete_insightcachingstate (#70453, deployed 2026-07-14), which kept the table alive
# for one deploy cycle so in-flight old pods could keep writing. That window has long passed:
# nothing reads or writes the table, and the surviving FK on dashboard_tile_id was the last
# thing making DashboardTile hard-deletes fail. Dropping the table removes it for good.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("product_analytics", "0002_delete_insightcachingstate"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS posthog_insightcachingstate;",
            reverse_sql=migrations.RunSQL.noop,  # obsolete table, no reverse
        ),
    ]
