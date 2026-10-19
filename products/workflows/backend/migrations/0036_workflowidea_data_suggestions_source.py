from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0035_hogflowbatchjob_waiting_index"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workflowidea",
            name="source",
            field=models.CharField(
                choices=[
                    ("manual", "Manual"),
                    ("scout", "Scout"),
                    ("data_suggestions", "Data suggestions"),
                ],
                default="manual",
                max_length=20,
            ),
        ),
    ]
