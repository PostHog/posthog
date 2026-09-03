from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0115_teamtasksconfig_usertasksconfig"),
    ]

    operations = [
        migrations.AddField(
            model_name="teamtasksconfig",
            name="email_inbound_token",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
    ]
