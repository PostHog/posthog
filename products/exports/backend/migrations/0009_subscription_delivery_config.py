from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exports", "0008_exportedasset_source_authentication"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="delivery_config",
            field=models.JSONField(db_default={}, default=dict),
        ),
        migrations.AddField(
            model_name="subscriptiondelivery",
            name="slack_gallery_delivery_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
