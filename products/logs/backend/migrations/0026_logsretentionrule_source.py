from django.db import migrations, models
from django.db.models import Value


class Migration(migrations.Migration):
    dependencies = [
        ("logs", "0025_alter_logsalertconfiguration_team_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="logsretentionrule",
            name="source",
            field=models.CharField(
                choices=[("logs", "Logs"), ("spans", "Spans")],
                db_default=Value("logs"),
                default="logs",
                max_length=16,
            ),
        ),
    ]
