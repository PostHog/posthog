# State-only removal of DailyBriefing. The today_dailybriefing table is kept so code still
# running during the rolling deploy can use it; a follow-up migration drops it after a full
# deploy cycle (see safe-django-migrations.md, "Dropping Tables").

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("today", "0002_todayhighlights"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name="DailyBriefing",
                ),
            ],
            database_operations=[],
        ),
    ]
