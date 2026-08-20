from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("exports", "0007_alter_exportedasset_export_format")]

    operations = [
        migrations.AddField(
            model_name="exportedasset",
            name="source_personal_api_key_id",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
