from django.db import migrations

TRACK_KEY_RENAMES = {
    "hog_streak": "streak",
    "loyal_hog": "loyalty",
    "data_hog": "explorer",
    "detective_hog": "detective",
    "goal_hog": "conversions",
    "mighty_hog": "traffic",
}


def rename_track_keys(apps, schema_editor):
    Progress = apps.get_model("web_analytics", "WebAnalyticsAchievementProgress")
    for old_key, new_key in TRACK_KEY_RENAMES.items():
        Progress.objects.filter(track_key=old_key).update(track_key=new_key)


def revert_track_keys(apps, schema_editor):
    Progress = apps.get_model("web_analytics", "WebAnalyticsAchievementProgress")
    for old_key, new_key in TRACK_KEY_RENAMES.items():
        Progress.objects.filter(track_key=new_key).update(track_key=old_key)


class Migration(migrations.Migration):
    dependencies = [
        ("web_analytics", "0003_webanalyticsinteraction"),
    ]

    operations = [
        migrations.RunPython(rename_track_keys, revert_track_keys),
    ]
