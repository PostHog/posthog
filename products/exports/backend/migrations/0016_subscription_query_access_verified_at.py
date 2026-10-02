from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exports", "0015_exportedasset_session_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="query_access_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
