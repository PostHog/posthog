from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("review_hog", "0023_reviewreport_unclassified_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="reviewreport",
            name="published_head_shas",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
