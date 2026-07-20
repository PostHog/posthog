from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("review_hog", "0019_alter_reviewreportartefact_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="reviewusersettings",
            name="resolve_comments",
            field=models.BooleanField(db_default=True, default=True),
        ),
    ]
