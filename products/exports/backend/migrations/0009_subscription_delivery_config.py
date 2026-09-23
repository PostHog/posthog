from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exports", "0008_exportedasset_source_authentication"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="delivery_config",
            field=models.JSONField(default=dict),
        ),
    ]
