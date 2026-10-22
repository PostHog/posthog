from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0035_hogflowbatchjob_waiting_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="hogflow",
            name="disabled_from_active",
            field=models.BooleanField(default=False, db_default=False),
        ),
    ]
