from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("error_tracking", "0055_errortrackingissuetagrule_color")]

    operations = [
        migrations.AddField(
            model_name="errortrackingissue",
            name="resolved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="errortrackingissue",
            name="resolved_until",
            field=models.TextField(
                blank=True,
                choices=[("next_occurrence", "Next occurrence"), ("new_release", "New release")],
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="errortrackingissue",
            name="latest_release_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="errortrackingissue",
            name="latest_release_created_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
