from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notebooks", "0026_widget_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="notebooknoderun",
            name="warehouse_table_name",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
    ]
