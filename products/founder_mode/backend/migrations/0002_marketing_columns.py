from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("founder_mode", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="founderproject",
            name="marketing_page",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="founderproject",
            name="marketing_steps",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
