from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("event_definitions", "0002_schemapropertygroupproperty_is_optional_in_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="schemapropertygroupproperty",
            name="validation_rules",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
