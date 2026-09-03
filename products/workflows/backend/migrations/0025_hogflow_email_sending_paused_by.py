from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0024_hogflow_email_sending_paused_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="hogflow",
            name="email_sending_paused_by",
            field=models.CharField(blank=True, db_default="", default="", max_length=16),
        ),
    ]
