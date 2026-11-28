from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("error_tracking", "0055_errortrackingissuetagrule_color")]

    operations = [
        migrations.AddField(
            model_name="errortrackingissue",
            name="last_received_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="errortrackingsettings",
            name="auto_resolve_after_days",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
