from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notebooks", "0035_kernelruntime_read_scopes"),
    ]

    operations = [
        migrations.AddField(
            model_name="notebookrun",
            name="credential_denied_scopes",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="notebooknoderun",
            name="credential_denied_scopes",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
