from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0018_transactionalemailkey_source_origin"),
    ]

    operations = [
        migrations.AddField(
            model_name="emailhardbounce",
            name="last_delivered_at",
            field=models.DateTimeField(null=True),
        ),
    ]
