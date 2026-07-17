from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0008_teamworkflowsconfig"),
    ]

    operations = [
        migrations.AddField(
            model_name="hogflow",
            name="action_redirects",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
