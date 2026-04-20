from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("event_definitions", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="schemapropertygroupproperty",
            name="is_optional_in_types",
            field=models.BooleanField(default=False),
        ),
    ]
