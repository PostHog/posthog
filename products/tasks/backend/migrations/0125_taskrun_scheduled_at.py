from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0124_drop_retired_code_home_tables"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrun",
            name="scheduled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
