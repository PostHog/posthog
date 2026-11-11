from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("stamphog", "0013_review_on_clean_external_review"),
    ]

    operations = [
        migrations.AddField(
            model_name="stamphogrepoconfig",
            name="routing_shared_behavior_labels",
            field=models.JSONField(db_default={}, default=dict),
        ),
    ]
