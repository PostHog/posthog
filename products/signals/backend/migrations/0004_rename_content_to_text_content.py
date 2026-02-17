from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0003_alter_signalreport_status_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="signalreportartefact",
            name="content",
        ),
        migrations.AddField(
            model_name="signalreportartefact",
            name="text_content",
            field=models.TextField(default="{}"),
            preserve_default=False,
        ),
    ]
