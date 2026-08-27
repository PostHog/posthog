from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notebooks", "0016_merge_20260827_1013"),
    ]

    operations = [
        migrations.AddField(
            model_name="generatedwidgetversion",
            name="prompt_history",
            field=models.JSONField(default=list),
        ),
        migrations.RemoveIndex(
            model_name="notebookwidgetinstance",
            name="nb_widget_instance_widget",
        ),
        migrations.AddIndex(
            model_name="notebookwidgetinstance",
            index=models.Index(fields=["team", "widget", "-updated_at"], name="nb_widget_instance_recent"),
        ),
    ]
