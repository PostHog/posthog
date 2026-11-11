from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notebooks", "0029_squash_2026_11_02_schema_addons"),
    ]

    operations = [
        migrations.AddField(
            model_name="notebooknoderun",
            name="warehouse_table_name",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
    ]
