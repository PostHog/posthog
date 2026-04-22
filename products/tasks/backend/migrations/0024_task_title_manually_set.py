from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0023_alter_codeinvite_id_alter_codeinviteredemption_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="title_manually_set",
            field=models.BooleanField(default=False),
        ),
    ]
