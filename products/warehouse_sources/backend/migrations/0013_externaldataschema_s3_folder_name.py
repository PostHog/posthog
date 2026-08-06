from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0012_alter_externaldatasource_source_type_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="s3_folder_name",
            field=models.CharField(blank=True, max_length=400, null=True),
        ),
    ]
