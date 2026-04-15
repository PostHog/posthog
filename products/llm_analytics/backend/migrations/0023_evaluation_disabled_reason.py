from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("llm_analytics", "0022_reviewqueue_reviewqueueitem_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluation",
            name="disabled_reason",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]
