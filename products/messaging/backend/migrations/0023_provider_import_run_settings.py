from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0022_messagerecipientpreference_lower_identifier_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="providerimportrun",
            name="settings",
            field=models.JSONField(db_default={}, default=dict),
        ),
    ]
