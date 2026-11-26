from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notebooks", "0034_app_release_sql_rows"),
    ]

    operations = [
        migrations.AddField(
            model_name="kernelruntime",
            name="read_scopes",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
