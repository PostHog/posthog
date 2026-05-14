from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orchestra", "0003_deployment"),
    ]

    operations = [
        migrations.AddField(
            model_name="deployment",
            name="registered_executions",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
