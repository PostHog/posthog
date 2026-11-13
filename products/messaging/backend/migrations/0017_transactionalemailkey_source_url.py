from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0016_first_code_send"),
    ]

    operations = [
        migrations.AddField(
            model_name="transactionalemailkey",
            name="source_url",
            field=models.URLField(blank=True, max_length=2048, null=True),
        ),
    ]
