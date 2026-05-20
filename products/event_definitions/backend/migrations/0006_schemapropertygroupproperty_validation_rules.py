from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("event_definitions", "0005_eventdefinition_rename_promoted_to_primary"),
    ]

    operations = [
        migrations.AddField(
            model_name="schemapropertygroupproperty",
            name="validation_rules",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AlterField(
            model_name="schemapropertygroupproperty",
            name="property_type",
            field=models.CharField(
                choices=[
                    ("DateTime", "DateTime"),
                    ("String", "String"),
                    ("Numeric", "Numeric"),
                    ("Boolean", "Boolean"),
                    ("Object", "Object"),
                    ("Any", "Any"),
                ],
                max_length=50,
            ),
        ),
    ]
