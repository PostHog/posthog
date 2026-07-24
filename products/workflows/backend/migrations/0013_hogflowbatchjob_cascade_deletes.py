import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0012_hogflow_encrypted_inputs"),
    ]

    operations = [
        migrations.AlterField(
            model_name="hogflowbatchjob",
            name="hog_flow",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="workflows.hogflow"),
        ),
        migrations.AlterField(
            model_name="hogflowbatchjob",
            name="team",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team"),
        ),
    ]
