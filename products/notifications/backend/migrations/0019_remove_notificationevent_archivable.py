from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0018_alter_notificationevent_notification_type"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="notificationevent",
                    name="archivable",
                ),
            ],
        ),
    ]
