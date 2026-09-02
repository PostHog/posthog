from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0022_hogflow_origin_product"),
    ]

    operations = [
        migrations.AddField(
            model_name="hogflow",
            name="email_sending_paused_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hogflow",
            name="email_sending_paused_reason",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
        migrations.AddField(
            model_name="hogflow",
            name="email_sending_resumed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hogflow",
            name="email_sending_warned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
