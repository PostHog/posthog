from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0003_alter_signalreport_status_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="signalreportartefact",
            old_name="content",
            new_name="text_content",
        ),
    ]
