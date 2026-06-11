from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analytics", "0027_increase_skill_description_max_length"),
    ]

    operations = [
        migrations.AlterField(
            model_name="clusteringjob",
            name="analysis_level",
            field=models.CharField(
                choices=[("trace", "trace"), ("generation", "generation"), ("evaluation", "evaluation")],
                max_length=20,
            ),
        ),
    ]
